# Doomsday Watch

Checks https://cinema.mv every 5 minutes. When Avengers: Doomsday tickets go on sale, it emails you and then switches itself off.

## Setup (about 10 minutes, free)

1. **Gmail App Password.** Turn on 2-Step Verification for your Google account. Then go to https://myaccount.google.com/apppasswords, create one called "Doomsday Watch" and copy the 16-character code.
2. **GitHub repo.** Create a new **public** repository on github.com. Public repos get unlimited free Actions minutes. Your password stays hidden in Secrets either way. Upload all of these files and keep the `.github/workflows/` folder path as it is.
3. **Secrets.** In the repo go to Settings → Secrets and variables → Actions → New repository secret, and add:
   - `GMAIL_USER`: your Gmail address
   - `GMAIL_APP_PASSWORD`: the 16-character code
   - `NOTIFY_TO`: the address that should get the alert (if you leave this out, it goes to `GMAIL_USER`)
4. **Test it.** Go to Actions → Doomsday Watch → Run workflow, tick **"Send a test email"**, then run it. You should get a test email within about a minute.
5. **Check a real run.** Run it again without the tick. Open the run log to see what the checker found on cinema.mv, for example `Not yet: 'doomsday' is listed as coming soon`.

After that it runs on its own every 5 minutes.

## Options (in `.github/workflows/doomsday-watch.yml`)

- `ALERT_ON_ANY: "1"` emails you as soon as the film's name appears anywhere on the site, even under "Coming soon". This is the safest setting if you don't want to miss the start of sales.
- `MOVIE_KEYWORD` sets the text the checker looks for. The default is `doomsday`.

## Good to know

- GitHub sometimes runs scheduled jobs a few minutes late when it's busy, so expect a check every 5 to 15 minutes.
- If the site is down, that run is skipped quietly and the next run tries again.
- After it emails you, the workflow disables itself. To start it again, go to Actions → Doomsday Watch → Enable workflow.
