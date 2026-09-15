# Off-machine backups

Ten snapshots on the same disk as the database survive a bad UPDATE. They do
not survive a lost disk, and production is one VM in a house.

**What is irreplaceable is smaller than it looks.** The photographs are forty
gigabytes and re-downloadable; the database is megabytes. What cannot be
recovered from anywhere is `security.password_pepper` in `config.yaml` — it is
HMAC'd into every password before Argon2 and stored nowhere else, so a database
restored without that exact string has no working logins, including yours. It
also decrypts the TOTP secrets. That is why the nightly bundle carries the
config and not just the dump.

## Which account runs it

`milsurp`, not `root` and not a login account. It already owns everything the
job touches:

| | mode | owner |
|---|---|---|
| `/etc/milsurp` | 0750 | milsurp:milsurp |
| `/etc/milsurp/config.yaml` | 0600 | milsurp:milsurp |
| `/etc/milsurp/backups` | 0700 | milsurp |

An ordinary login account cannot read either, and adding it to the `milsurp`
group would not help — 0600 on the file and 0700 on the directory give the
group nothing. Making it work would mean loosening the permissions on the file
holding the pepper, the JWT secret and the database password, which is the
trade this is trying not to make.

The key cannot live in `milsurp`'s home: that is `/opt/milsurp`, which dpkg
owns and an upgrade rewrites. `/etc/milsurp` is `milsurp`'s own and survives
upgrades, so the key and the `known_hosts` file go there.

## Setting it up

```sh
# 1. Put the private key where milsurp can read it and an upgrade will not
#    touch it. This is the *private* half — no .pub — whose public half is
#    already in bceverly@192.168.4.10:~/.ssh/authorized_keys.
sudo install -m 0600 -o milsurp -g milsurp ~/.ssh/id_rsa /etc/milsurp/backup_key
sudo install -m 0600 -o milsurp -g milsurp /dev/null /etc/milsurp/known_hosts

# 2. Prove the VM can reach the NAS *as milsurp*, before trusting cron with it.
sudo -u milsurp ssh -i /etc/milsurp/backup_key \
  -o UserKnownHostsFile=/etc/milsurp/known_hosts -o StrictHostKeyChecking=accept-new \
  bceverly@192.168.4.10 'echo reachable; ls -d /zfs-pool/backup'

# If that fails with "no mutual signature algorithm", the key is an older RSA
# one and the NAS runs OpenSSH 8.8 or newer, which stopped accepting SHA-1
# signatures by default. Confirm with -o PubkeyAcceptedKeyTypes=+ssh-rsa; the
# better fix is an ed25519 key generated for this job, which sidesteps it.

# 3. Somewhere to log, writable by milsurp.
sudo install -m 0640 -o milsurp -g adm /dev/null /var/log/milsurp-offsite.log

# 4. Install the scripts and the schedule.
sudo install -m 0755 offsite-backup.sh /usr/local/bin/milsurp-offsite
sudo install -m 0755 offsite-images.sh /usr/local/bin/milsurp-offsite-images
sudo install -m 0644 milsurp-offsite   /etc/cron.d/milsurp-offsite

# 5. Run it once by hand. A cron job you have never run is a plan, not a backup.
sudo -u milsurp env NAS_TARGET=bceverly@192.168.4.10 \
  NAS_PATH=/zfs-pool/backup/milsurp KEEP=10 milsurp-offsite
```

## Two directories, not one

The nightly job writes bundles to `/zfs-pool/backup/milsurp` and keeps ten.
The weekly image mirror writes to `/zfs-pool/backup/milsurp-images`, and it
**must** be a different directory: it runs `rsync --delete`, so pointed at the
first one it would delete every database bundle there on its first pass.

## Encrypting it

The bundle carries the pepper, the JWT secret and the database password in
clear text. `scp` protects it in flight; nothing protects it at rest on the
NAS. If the pool is shared, or replicated somewhere else in turn:

```sh
sudo sh -c 'umask 077; head -c 32 /dev/urandom | base64 > /etc/milsurp/backup_pass'
sudo chown milsurp:milsurp /etc/milsurp/backup_pass
# then add to /etc/cron.d/milsurp-offsite:
#   GPG_PASSPHRASE_FILE=/etc/milsurp/backup_pass
```

**Put that passphrase in your password vault before relying on it.** A bundle
you cannot decrypt is not a backup, and the machine holding the only copy of
the passphrase is the machine you are backing up.

## Restoring

**[deploy/RESTORE.md](../RESTORE.md) is the runbook**, and it is the one to
follow: it has been walked end to end against a real bundle off the NAS, it
covers the migration step this shorthand leaves out, and it records the way the
restore fails if you reach for the obvious `pg_restore` flags. The short form,
for somebody who has read it before:

```sh
tar -xzf milsurp-20260915-031000.tar.gz          # or: gpg -d …tar.gz.gpg | tar -xz
sudo install -m 0600 -o milsurp -g milsurp config.yaml /etc/milsurp/config.yaml
sudo -u postgres pg_restore -d milsurp --clean --if-exists milsurp-20260915-031000.dump
sudo -u milsurp env MILSURP_ENV=production \
  /opt/milsurp/.venv/bin/python /opt/milsurp/scripts/dbupdate.py
sudo systemctl restart milsurp
```

`dbupdate.py` is not optional. A backup is older than the code it is being
restored under, often by several migrations, and the schema has to be brought
forward before the application will start.

The photographs come back from the weekly mirror, or from `backend/cli.py
fetch-photos` given time and the vendors' patience.

## What is not covered

A restore *has* now been done end to end — see the runbook — so this is a
proven backup rather than a copy of some files. What that drill did not prove:

- **The encrypted path.** The bundle restored was a plain `.tar.gz`. If you
  set `GPG_PASSPHRASE_FILE`, do the drill again; a passphrase nobody has ever
  decrypted with is a guess.
- **A bare-metal rebuild.** The restore went into a throwaway container, not a
  freshly installed machine. The package install, the certificate and the DNS
  are still untested as one sequence.
- **The photographs.** The image mirror has never been rsynced back.
