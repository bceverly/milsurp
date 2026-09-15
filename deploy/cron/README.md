# Off-machine backups

Ten snapshots on the same disk as the database survive a bad UPDATE. They do
not survive a lost disk, and production is one VM in a house.

**What is irreplaceable is smaller than it looks.** The photographs are forty
gigabytes and re-downloadable; the database is megabytes. What cannot be
recovered from anywhere is `security.password_pepper` in `config.yaml` — it is
HMAC'd into every password before Argon2 and stored nowhere else, so a database
restored without that exact string has no working logins, including yours. That
is why the nightly bundle carries the config and not just the dump.

## Setting it up

Everything runs as root: the snapshot directory is `0700 milsurp` and
`config.yaml` is `0600`.

```sh
# 1. A key for this and nothing else, with no passphrase so cron can use it.
sudo ssh-keygen -t ed25519 -f /root/.ssh/id_milsurp_backup -N '' -C milsurp-offsite
sudo cat /root/.ssh/id_milsurp_backup.pub     # add this to the NAS account

# 2. Prove the VM can actually reach the NAS, before trusting a cron job to.
sudo ssh -i /root/.ssh/id_milsurp_backup -o BatchMode=yes backup@nas.lan 'echo reachable'

# 3. Install the scripts and the schedule.
sudo install -m 0755 offsite-backup.sh  /usr/local/sbin/milsurp-offsite
sudo install -m 0755 offsite-images.sh  /usr/local/sbin/milsurp-offsite-images
sudo install -m 0644 milsurp-offsite    /etc/cron.d/milsurp-offsite
sudoedit /etc/cron.d/milsurp-offsite           # set NAS_TARGET and the paths

# 4. Run it once by hand. A cron job you have never run is a plan, not a backup.
sudo NAS_TARGET=backup@nas.lan NAS_PATH=/volume1/backups/milsurp milsurp-offsite
```

## Encrypting it

The bundle carries the pepper, the JWT secret and the database password in
clear text. `scp` protects it in flight; nothing protects it at rest on the
NAS. If the NAS is shared, or backed up somewhere else in turn:

```sh
sudo sh -c 'umask 077; head -c 32 /dev/urandom | base64 > /root/.milsurp-backup-pass'
# then add to /etc/cron.d/milsurp-offsite:
#   GPG_PASSPHRASE_FILE=/root/.milsurp-backup-pass
```

**Put that passphrase in your password vault before you rely on it.** A bundle
you cannot decrypt is not a backup, and the machine holding the only copy of
the passphrase is the machine you are backing up.

## Restoring

```sh
tar -xzf milsurp-20260915-031000.tar.gz          # or: gpg -d …tar.gz.gpg | tar -xz
sudo install -m 0600 -o milsurp -g milsurp config.yaml /etc/milsurp/config.yaml
sudo -u postgres pg_restore -d milsurp --clean --if-exists milsurp-20260915-031000.dump
sudo systemctl restart milsurp
```

The photographs come back from the weekly mirror, or from
`milsurp fetch-photos` given time and the vendors' patience.

## What is not covered

A restore has never been done end to end on this deployment. Until it has,
this is a copy of some files rather than a proven backup — the roadmap says the
same thing and it stays true until somebody rebuilds a machine from one.
