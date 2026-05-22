# milkbot
random personal discord bot

## environment

- `DISCORD_TOKEN`: Discord bot token
- `BOT_DEVELOPER_ID`: bot developer Discord user ID
- `X_TOKEN`: X API bearer token used by `/트위터업뎃`
- `TWITTER_UPDATE_POLL_SECONDS`: X post check interval, default `60`

ideas/TODOs

- v fix the gameplaza live checker thingy

- choose song by random \
  user can choose range of difficulty, randomly chooses ridiculus levels at small chance \
  maybe use zetaraku.dev (why make db when there is one publically)

- song finder
  based on user's filter setting, find in which index the designated song locates \
  e.g.) Based on rating sorting, "Enchanted Love" MAS will be at 187/365 on variety folder \
  -> maybe extend to find the most optimal way to find song?
  + make it possible to import json from zetaraku.dev

  thinking about using maishift for gathering user's exact score \
  sort only by general setting (date, etc) when maishift is not connected \
  ^ second thought, general sorting based indexing must always be visible \
  and... I do not have a db for now

- utage dict
  returns info about utage charts \
  filters utage for 2/3/4 players for 1/2 cabinet

- chiho calculator
  based on various conditions, calculate expected credit and time to finish each chiho \
  (or user can input current chiho + progressed km)

- clip generator (w/ external program)
  checks gameplay vid -> reports every play result recorded and timestamp
  (make external program that can generate gameplay clip with result above)

- dev debuging menu
  seperate every message visible to user as json file \
  allow me to check on milkbot dm \
  message should be legacy text command form? idk \
  iirc slash is visible to everyone \
  (and only i want to use those so) \
  ㄴ command to shift this to dm between me and milkbot to specific channel \
  way for me to message as milkbot

- git push notification
  dm me when bot gets update

- v check performai international account message

- smth fun idk
