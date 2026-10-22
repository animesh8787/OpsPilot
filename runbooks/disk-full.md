# Disk Full

**Alert:** disk usage above 90%, write failures, no space left on device.
**Keywords:** disk full space storage inode logs no space left

## Triage
1. Run df -h and du -sh on /var/log to find the largest consumers.
2. Check that log rotation is working.

## Mitigation
- Delete or compress old logs.
- Expand the volume.
