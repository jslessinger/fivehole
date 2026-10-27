# Five Hole

Every goalie has one. So does every defense.

**The Crease (NHL):** each night's games with the goalie expected in net, his game log,
the last seven games for both teams, home and road splits, special teams and injuries.
**The Gridiron (NFL):** yards allowed by position for every defense, weekly matchups,
Best Bets and injury-aware depth charts.

Everything refreshes automatically through GitHub Actions: NHL data every hour, NFL
data daily and around game days.

## What's in here

| File | What it does |
| --- | --- |
| `index.html` | The whole website (pages, design and logic). |
| `data.json` | The stats the site reads. Rebuilt automatically. |
| `scripts/build_data.py` | Downloads nflverse data and writes `data.json`. |
| `nhl.json` | The NHL data the site reads. Created and refreshed automatically. |
| `scripts/build_nhl.py` | Downloads NHL data (NHL web and stats APIs, ESPN injuries) and writes `nhl.json`. |
| `.github/workflows/update-stats.yml` | Runs the script on a schedule and publishes the site. |

## One-time setup (about 10 minutes)

1. **Create a GitHub account** at github.com if you don't have one.
2. **Create a repository.** Click **+** (top right) → **New repository**.
   Name it `fivehole`, set it to **Public**, and click **Create repository**.
3. **Upload the files.** Unzip the zip file. You'll get these items:
   `index.html`, `data.json`, `README.md`, `update-stats.yml` and a `scripts`
   folder (holding `build_data.py` and `build_nhl.py`). On the new repository's page click **uploading an existing file**,
   select **all five items** and drag them into the upload box (drag the items
   themselves, not a folder that contains them). Click **Commit changes**.
4. **Move the workflow file into place.** GitHub only runs automation files
   stored in a folder called `.github/workflows`.
   - In your repository, click `update-stats.yml`, then click the **pencil**
     icon (Edit) at the top right of the file.
   - At the top of the editor is the file name box showing `update-stats.yml`.
     Click at the very **start** of the name and type `.github/workflows/`
     (GitHub turns each part into a folder as you type the `/`), so the path
     reads `.github/workflows/update-stats.yml`.
   - Click **Commit changes**, then **Commit changes** again.
5. **Turn on GitHub Pages.** Go to **Settings → Pages**. Under
   **Build and deployment → Source**, choose **GitHub Actions**.
6. **Run the first update.** Open the **Actions** tab (click the enable button if
   GitHub asks). Click **Update stats and publish site** on the left →
   **Run workflow** → **Run workflow**. It takes 2–4 minutes.
7. **Open your site** at `https://YOUR-USERNAME.github.io/fivehole/`.

Your repository's main page should end up showing `.github`, `scripts`,
`README.md`, `data.json` and `index.html` (plus `nhl.json` after the first run). If you see a single folder you have to
click into instead, the files were uploaded one level too deep: delete the
repository (Settings → General → Delete this repository) and repeat from step 2.

## Moving from an older repository (soft-spot or achilles)

Set up `fivehole` with the steps above, then retire the old repository so two
copies aren't updating on a schedule:

- **Delete it:** old repository → **Settings → General** → scroll to the bottom →
  **Delete this repository**. Its old web address stops working.
- **Or keep it but stop it:** old repository → **Actions** →
  **Update stats and publish site** → **⋯** (top right) → **Disable workflow**.


## NHL data

The NHL board refreshes every hour. It uses the NHL's public web and stats APIs
for standings, schedules, rosters, goalie stats and box scores, and ESPN's public
injury and odds feeds. A goalie is **Confirmed** when he's named the starter in the NHL's official
game lineup (filed about 20-30 minutes before puck drop) or has started the game,
**Expected** when ESPN lists him as the probable starter, and **Projected** when
Five Hole makes its own pick from recent starts, back-to-backs and injuries.
In the evening the NHL update runs every 10 minutes to catch official lineups.

### Entering starting goalies yourself (goalies.txt)

When you see a starter confirmed (on GoaliePost, RotoWire, a team account or a
beat reporter), add a line to `goalies.txt` in the repository and commit:

    PHI Joseph Woll                   next PHI game, shown as Confirmed
    CGY Dustin Wolf expected          shown as Expected
    2026-10-28 PHI Dan Vladar         a specific date

The site updates in a few minutes. Old lines are ignored once the game is played.
The NHL's official lineup, filed about 20-30 minutes before puck drop, always wins.

### Editing goalies on the site itself

You can set starters right on Five Hole instead of editing `goalies.txt` by hand.

One-time setup on each device you'll edit from:

1. On GitHub, open your profile picture → **Settings** → **Developer settings** →
   **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
2. Name it `Five Hole editor`, pick an expiration (up to a year), and under
   **Repository access** choose **Only select repositories** → `fivehole`.
3. Under **Permissions → Repository permissions**, set **Contents** to
   **Read and write**. Leave everything else as is.
4. Click **Generate token** and copy it (it starts with `github_pat_`).
5. On your site, open **The Crease**, click **Editor sign-in** at the bottom,
   paste the token, check the repository reads `jslessinger/fivehole`, and click
   **Sign in**.

From then on, every game page shows **Set starter** under each goalie card: pick the
goalie and Confirmed or Expected, then **Save** (or **Clear** to go back to the
site's own pick). It updates `goalies.txt` for you, and the site refreshes for
everyone in a few minutes. Visitors never see these controls.

The token is stored only in that browser. Use **Sign out on this device** on shared
computers, and if a token is ever exposed, delete it on GitHub under Fine-grained
tokens; that instantly disables it.

### Odds

Each game page shows the current moneyline, puck line and total from ESPN's free
public game feed (whichever sportsbook ESPN partners with). It refreshes hourly
with the rest of the NHL data. No key or account is needed.

## How updates happen

The workflow runs every morning, after each Sunday window, after Sunday and
Monday night games, and Wednesday–Friday evenings when injury reports come out.
Each run downloads the latest stats, injuries, rosters, depth charts and
schedule, saves `data.json` and republishes the site. You can force an update
any time from **Actions → Update stats and publish site → Run workflow**.

nflverse usually posts a game's stats within a few hours of the final whistle,
so Sunday numbers are typically complete by Monday morning.

The script picks the season by date (August onward counts as that year's
season). To force a particular season, change the `Build data.json` step in the
workflow to `run: SEASON=2026 python scripts/build_data.py`.

## Getting found in Google

- In **Settings → Pages** you can add a **custom domain** (for example
  `fivehole.app`) after buying one from any registrar; GitHub shows the
  DNS records to add.
- Submit your site at [Google Search Console](https://search.google.com/search-console)
  so Google indexes it. New sites usually appear in results within a few days
  to a few weeks.

## Running it on your own computer

```bash
pip install pandas
python scripts/build_data.py
python -m http.server 8000
```

Then open http://localhost:8000. (Opening `index.html` directly from disk
won't work, because browsers block it from reading `data.json`.)

## Credits

Player stats, play-by-play, injuries, rosters, depth charts and schedules:
nflverse (CC-BY-4.0). Not affiliated with the NFL or any team.
