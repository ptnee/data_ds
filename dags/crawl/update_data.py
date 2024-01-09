import os

import pandas as pd

from datetime import datetime, timedelta
from pytz import timezone

# change working directory to project root when running from notebooks folder to make it easier to import modules
# and to access sibling folders
os.chdir('..')

from crawl_data import (
    activate_web_driver,
    scrape_to_dataframe,
    convert_columns,
    combine_home_visitor,
)

from pathlib import Path  #for Windows/Linux compatibility
BASE_PATH= "/opt/airflow/dags/"

games_old = pd.read_csv(f"{BASE_PATH}data/games.csv")

# Find the last date and season in the current dataset
last_date = games_old["GAME_DATE_EST"].max()
last_season = games_old["SEASON"].max()

# remove the time from the date
last_date = last_date.split(" ")[0]

# Determine the date of the next day to begin scraping from
start_date = datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)

# determine what season we are in currently
today = datetime.now(timezone('EST')) #nba.com uses US Eastern Standard Time
if today.month >= 10:
    current_season = today.year
else:
    current_season = today.year - 1

# determine which seasons we need to scrape to catch up the data
seasons = list(range(last_season, current_season+1))


print("Last date in dataset: ", last_date)
print("Last season in dataset: ", last_season)
print("Current season: ", current_season)
print("Seasons to scrape: ", seasons)
print("Start date: ", start_date)

# if the last date in the dataset is today, then we don't need to scrape any new data
if start_date > datetime.now():
    print("No new data to scrape")
    exit()
driver = activate_web_driver('chromium')
SCRAPINGANT_API_KEY = ""


def update_games(driver, season, start_date, end_date) -> pd.DataFrame:
    season_types = ["Regular+Season", "PlayIn", "Playoffs"]

    all_season_types = pd.DataFrame()

    for season_type in season_types:

        # new_games = pd.DataFrame()

        df = scrape_to_dataframe(api_key=SCRAPINGANT_API_KEY, driver=driver, Season=season, DateFrom=start_date,
                                 DateTo=end_date, season_type=season_type)

        if not (df.empty):
            df = convert_columns(df)
            df = combine_home_visitor(df)
            all_season_types = pd.concat([all_season_types, df], axis=0)

    return all_season_types
    # return new_games

new_games = pd.DataFrame()
df_season = pd.DataFrame()

for season in seasons:
    end_date = datetime.strptime(f"{season+1}-08-01", "%Y-%m-%d") # use August 1st to get all games from the current season
    print(f"Scraping season {season} from {start_date} to {end_date}")
    df_season = update_games(driver, str(season), str(start_date), str(end_date))
    new_games = pd.concat([new_games, df_season], axis=0)
    start_date = datetime.strptime(f"{season+1}-10-01", "%Y-%m-%d") # if more than 1 season, reset start date to beginning of next season

driver.close()

games = pd.concat([games_old, new_games], axis=0)

new_games.to_csv(f"{BASE_PATH}data/new_games.csv")

games.to_csv(f"{BASE_PATH}data/games.csv")
