# Restoring from a backup

**This has been done end to end.** On 15 September 2026 a bundle was taken off
the NAS, restored into a throwaway PostgreSQL 18 container, migrated from the
schema it was dumped at to the one the current code wants, and the application
was pointed at the result and asked to do real work. What follows is what was
actually run, with the one thing that went wrong left in — because it will go
wrong the same way next time.

The drill matters more than it sounds. Ten snapshots and a nightly copy to a
NAS are not a backup until somebody has rebuilt from one; until then they are a
copy of some files that nobody has ever read back.

## What is in a bundle

```
milsurp-20260915-204203.tar.gz
├── milsurp-20260915-204202.dump   # pg_dump custom format
└── config.yaml                    # and this is the half people forget
```

`config.yaml` carries `security.password_pepper`, which is HMAC'd into every
password before Argon2 and also derives the key that decrypts the TOTP secrets.
It is stored nowhere else. **A database restored without that exact file has no
working logins**, including the administrator's, and every enrolled
authenticator stops verifying. A database-only backup looks complete and is not.

## Practicing it (no risk to anything live)

A throwaway container is a better rehearsal than a scratch database on the
production host: it proves the dump restores into a *clean* server rather than
one that already happens to have the schema.

```sh
# 1. Fetch the newest bundle.
BUNDLE=$(ssh bceverly@192.168.4.10 'ls -1t /zfs-pool/backup/milsurp/milsurp-*.tar.gz | head -1')
mkdir -p ~/restore-drill && chmod 700 ~/restore-drill
scp "bceverly@192.168.4.10:$BUNDLE" ~/restore-drill/
cd ~/restore-drill && tar -xzf milsurp-*.tar.gz && chmod 600 config.yaml

# 2. A throwaway server. Port 55433 so it cannot be confused with a local one.
docker run -d --name milsurp-drill -e POSTGRES_PASSWORD=drill -e POSTGRES_DB=milsurp \
  -p 55433:5432 postgres:18
until docker exec milsurp-drill pg_isready -U postgres -q; do sleep 1; done

# 3. The role the dump's objects are owned by has to exist first.
docker exec milsurp-drill psql -U postgres -c "CREATE ROLE milsurp LOGIN PASSWORD 'drill';"
docker exec milsurp-drill psql -U postgres -c "DROP DATABASE IF EXISTS milsurp;"
docker exec milsurp-drill psql -U postgres -c "CREATE DATABASE milsurp OWNER milsurp;"

# 4. Restore.
docker cp milsurp-*.dump milsurp-drill:/tmp/restore.dump
docker exec milsurp-drill pg_restore -U postgres -d milsurp /tmp/restore.dump
```

### The thing that went wrong, and will again

The first attempt used `pg_restore --no-owner --role=milsurp` and produced
**218 errors**, the first of which was:

```
pg_restore: error: could not execute query: ERROR:  permission denied for schema public
LINE 1: CREATE TABLE public.alembic_version (
```

Since PostgreSQL 15 the `public` schema no longer grants `CREATE` to everyone,
so `--role=milsurp` switched to a role that could not create anything. Every
`CREATE TABLE` failed, and the two hundred-odd errors after it were constraints
and sequences for tables that were never made.

**Restore as the superuser and let the dump carry its own ownership.** No
`--role`, no `--no-owner`. The objects come back owned by `milsurp`, which is
what production has.

The failure is loud but the *shape* of it is misleading: `pg_restore` exits 0
and says "errors ignored on restore", so a restore that created nothing looks
like a restore that worked. Check the tables afterwards, always.

## Checking it worked

Row counts first, because they are quick and a truncated dump shows up here:

```sh
docker exec milsurp-drill psql -U postgres -d milsurp -c "
SELECT 'items' t, count(*) FROM items
UNION ALL SELECT 'sites', count(*) FROM sites
UNION ALL SELECT 'users', count(*) FROM users
UNION ALL SELECT 'item_photos', count(*) FROM item_photos ORDER BY 1;"
```

The drill produced 11,093 items, 28 sites, 1 user and 77,754 photo rows across
20 tables.

### Then bring the schema forward

**A backup is usually behind the code.** The bundle used here was dumped at
Alembic revision `0024` while the current tree wanted `0026`, which is the
ordinary case: backups are older than deployments. Point the application at the
restored database and migrate it.

```sh
cat > ~/restore-drill/drill-config.yaml <<'YAML'
database:
  engine: postgresql
  host: localhost
  port: 55433
  name: milsurp
  user: milsurp
  password: drill
images:
  directory: /tmp/milsurp-drill-images
backups: { enabled: false }
scheduler: { enabled: false }
email: { enabled: false }
YAML

MILSURP_ENV=dev MILSURP_CONFIG=~/restore-drill/drill-config.yaml \
  .venv/bin/python scripts/dbupdate.py
```

It should report `Upgraded 0024 -> 0026`, or that the database is already
current.

### And prove the application can use it

Row counts say the bytes arrived. This says the data is *usable*:

```sh
MILSURP_ENV=dev MILSURP_CONFIG=~/restore-drill/drill-config.yaml \
  .venv/bin/python -c "
import sys; sys.path.insert(0,'backend')
from sqlalchemy import select, func
from app.database import session_scope
from app.models import Item, Site
from app.services import armory
with session_scope() as s:
    print('sites :', s.execute(select(func.count(Site.id))).scalar())
    print('active:', s.execute(select(func.count(Item.id)).where(Item.is_active.is_(True))).scalar())
    print('armory rules:', len(armory.model_registry(s)))
    print('a match:', armory.match(s, 'Russian Izhevsk M91/30 Mosin Nagant 7.62x54R').model)
"
```

The drill got 28 sites, 10,873 active listings, 808 compiled armory rules, and
`Mosin-Nagant M91/30` back from the matcher.

### Clean up

The extracted `config.yaml` is production's, secrets and all.

```sh
docker rm -f milsurp-drill
rm -rf ~/restore-drill
```

## Restoring for real

Onto a rebuilt machine, after `apt install milsurp` and creating the database:

```sh
cd /tmp && tar -xzf milsurp-20260915-204203.tar.gz     # or: gpg -d …gpg | tar -xz

# The config first: without it the restored accounts cannot sign in.
sudo install -m 0600 -o milsurp -g milsurp config.yaml /etc/milsurp/config.yaml

sudo -u postgres pg_restore -d milsurp --clean --if-exists milsurp-20260915-204202.dump
sudo -u milsurp env MILSURP_ENV=production \
  /opt/milsurp/.venv/bin/python /opt/milsurp/scripts/dbupdate.py
sudo systemctl restart milsurp
rm -f /tmp/config.yaml /tmp/milsurp-*.dump
```

`--clean --if-exists` because that database already exists; the practice run
above starts from an empty one and does not need it.

The photographs are **not** in the bundle. They come from the weekly mirror:

```sh
sudo -u milsurp rsync -a --info=progress2 \
  -e 'ssh -i /etc/milsurp/backup_key -o UserKnownHostsFile=/etc/milsurp/known_hosts' \
  bceverly@192.168.4.10:/zfs-pool/backup/milsurp-images/ /etc/milsurp/images/
```

or, given time and the vendors' patience, from the photo queue, which rebuilds
the store from URLs the database already holds:

```sh
sudo -u milsurp env MILSURP_ENV=production \
  /opt/milsurp/.venv/bin/python /opt/milsurp/backend/cli.py fetch-photos
```

## Worth repeating

After anything that changes the shape of a backup — a Postgres major version, a
move between engines, a change to what the bundle contains — because each of
those is a way for the dump to stop being readable by the thing that has to
read it, and the day you find out should not be the day you need it.
