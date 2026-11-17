# Milkbot deployments

For a maintainer-requested Milkbot patch, include the GitHub push and Ubuntu restart in the same task. Follow any deployment instructions the maintainer gives for that patch.

1. In the Windows checkout, verify the patch and inspect `git status --short`. Run `git add .` when every listed change belongs to the patch. If unrelated changes are present, stage only the patch files. Commit with a descriptive message and run `git push origin main`.
2. After the push succeeds, run `sudo /usr/local/bin/deploy_milkbot.sh` on the Ubuntu host.
3. Confirm the Ubuntu checkout is on the pushed commit using `git rev-parse HEAD` and that `systemctl is-active milkbot.service` reports `active` after the restart. Report the commit and deployment result.
