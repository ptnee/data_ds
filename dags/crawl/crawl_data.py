import pandas as pd
import numpy as np

import os

import asyncio

# if using scrapingant, import these
from scrapingant_client import ScrapingAntClient

# if using selenium and chrome, import these
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromiumService
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
# from webdriver_manager.core.utils import ChromeType
from webdriver_manager.chrome import ChromeDriverManager



from bs4 import BeautifulSoup as soup

from datetime import datetime, timedelta
from pytz import timezone

from pathlib import Path  # for Windows/Linux compatibility

DATAPATH = Path(r'data')

import time

from src.constants import (
    OFF_SEASON_START,
    REGULAR_SEASON_START,
    PLAYOFFS_START,
    NBA_COM_DROP_COLUMNS,  # columns to drop from nba.com boxscore table, either not used or already renamed to match our schema
    DAYS,  # number of days back to scrape for games, usually set to >1 to catch up in case of a failed run
)

BASE_PATH= "/opt/airflow/dags/"

def activate_web_driver(browser: str) -> webdriver:
    options = [
        "--headless",
        "--window-size=1920,1200",
        "--start-maximized",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--ignore-certificate-errors",
        "--disable-extensions",
        "--disable-popup-blocking",
        "--disable-notifications",
        "--remote-debugging-port=9222",
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36"
        "--disable-blink-features=AutomationControlled",
    ]

    service = ChromiumService(executable_path=f"{BASE_PATH}drive/chromedriver.exe")

    chrome_options = Options()
    for option in options:
        chrome_options.add_argument(option)

    driver = webdriver.Chrome(service=service, options=chrome_options)

    return driver


def get_new_games(SCRAPINGANT_API_KEY: str, driver: webdriver) -> pd.DataFrame:

    SEASON = ""  # no season will cause website to default to current season, format is "2022-23"
    TODAY = datetime.now(timezone('EST'))  # nba.com uses US Eastern Standard Time
    LASTWEEK = (TODAY - timedelta(days=DAYS))
    DATETO = TODAY.strftime("%m/%d/%y")
    DATEFROM = LASTWEEK.strftime("%m/%d/%y")


    CURRENT_MONTH = TODAY.strftime("%m")
    print(f"Current month is {CURRENT_MONTH}")
    if int(CURRENT_MONTH) >= OFF_SEASON_START and int(CURRENT_MONTH) < REGULAR_SEASON_START:
        # off-season, no games being played
        return pd.DataFrame()
    elif int(CURRENT_MONTH) < PLAYOFFS_START or int(CURRENT_MONTH) >= REGULAR_SEASON_START:
        season_types = ["Regular+Season"]
    elif int(CURRENT_MONTH) == PLAYOFFS_START:
        season_types = ["Regular+Season", "PlayIn", "Playoffs"]
    elif int(CURRENT_MONTH) > PLAYOFFS_START:
        season_types = ["Playoffs"]

    all_season_types = pd.DataFrame()

    for season_type in season_types:

        df = scrape_to_dataframe(api_key=SCRAPINGANT_API_KEY, driver=driver, Season=SEASON, DateFrom=DATEFROM,
                                 DateTo=DATETO, season_type=season_type)

        # perform basic data processing to align with table schema
        if not (df.empty):
            df = convert_columns(df)
            df = combine_home_visitor(df)
            all_season_types = pd.concat([all_season_types, df], axis=0)

    return all_season_types


def parse_ids(data_table: soup) -> tuple[pd.Series, pd.Series]:

    CLASS_ID = 'Anchor_anchor__cSc3P'  # determined by visual inspection of page source code

    links = data_table.find_all('a', {'class': CLASS_ID})

    links_list = [i.get("href") for i in links]

    team_id = pd.Series([i[-10:] for i in links_list if ('stats' in i)])
    game_id = pd.Series([i[-10:] for i in links_list if ('/game/' in i)])

    return team_id, game_id


def scrape_to_dataframe(api_key: str, driver: webdriver, Season: str, DateFrom: str = "NONE", DateTo: str = "NONE",
                        stat_type: str = 'standard', season_type: str = "Regular+Season") -> pd.DataFrame:

    if stat_type == 'standard':
        nba_url = "https://www.nba.com/stats/teams/boxscores?SeasonType=" + season_type
    else:
        nba_url = "https://www.nba.com/stats/teams/boxscores-" + stat_type + "?SeasonType=" + season_type

    if not Season:
        nba_url = nba_url + "&DateFrom=" + DateFrom + "&DateTo=" + DateTo
    else:
        if DateFrom == "NONE" and DateTo == "NONE":
            nba_url = nba_url + "&Season=" + Season
        else:
            nba_url = nba_url + "&Season=" + Season + "&DateFrom=" + DateFrom + "&DateTo=" + DateTo

    print(f"Scraping {nba_url}")

    # try 2 times to load page correctly; scrapingant can fail sometimes on it first try
    for i in range(1, 2):
        if api_key == "":  # if no api key, then use selenium
            driver.get(nba_url)
            time.sleep(10)
            source = soup(driver.page_source, 'html.parser')
        else:  # if api key, then use scrapingant
            client = ScrapingAntClient(token=api_key)
            result = client.general_request(nba_url)
            source = soup(result.content, 'html.parser')

        # the data table is the key dynamic element that may fail to load
        CLASS_ID_TABLE = 'Crom_table__p1iZz'  # determined by visual inspection of page source code
        data_table = source.find('table', {'class': CLASS_ID_TABLE})

        if data_table is None:
            time.sleep(10)
        else:
            break

    if data_table is None:
        # if data table still not found, then there is no data for the date range
        # this may happen at the end of the season when there are no more games
        return pd.DataFrame()

        # check for more than one page
    CLASS_ID_PAGINATION = "Pagination_pageDropdown__KgjBU"  # determined by visual inspection of page source code
    pagination = source.find('div', {'class': CLASS_ID_PAGINATION})

    if api_key == "":
        if pagination is not None:

            CLASS_ID_DROPDOWN = "DropDown_select__4pIg9"  # determined by visual inspection of page source code
            page_dropdown = driver.find_element(By.XPATH,
                                                "//*[@class='" + CLASS_ID_PAGINATION + "']//*[@class='" + CLASS_ID_DROPDOWN + "']")

            page_dropdown.send_keys("ALL")
            time.sleep(3)
            driver.execute_script('arguments[0].click()',
                                  page_dropdown)

            time.sleep(3)
            source = soup(driver.page_source, 'html.parser')
            data_table = source.find('table', {'class': CLASS_ID_TABLE})



    dfs = pd.read_html(str(data_table), header=0)
    df = pd.concat(dfs)

    TEAM_ID, GAME_ID = parse_ids(data_table)
    df['TEAM_ID'] = TEAM_ID
    df['GAME_ID'] = GAME_ID

    return df


def convert_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert columns names and formats to match main DataFrame schema

    Args:
        df (pd.DataFrame): the scraped dataframe "as is" from nba.com

    Returns:
        processed DataFrame
    """

    drop_columns = NBA_COM_DROP_COLUMNS
    df = df.drop(columns=drop_columns)

    mapper = {
        'Match Up': 'HOME',
        'Game Date': 'GAME_DATE_EST',
        'W/L': 'HOME_TEAM_WINS',
        'FG%': 'FG_PCT',
        '3P%': 'FG3_PCT',
        'FT%': 'FT_PCT',
    }
    df = df.rename(columns=mapper)

    df['HOME'] = df['HOME'].apply(lambda x: 0 if '@' in x else 1)

    df = df[df['HOME_TEAM_WINS'].notna()]

    df['HOME_TEAM_WINS'] = df['HOME_TEAM_WINS'].apply(lambda x: 1 if 'W' in x else 0)

    df['GAME_DATE_EST'] = pd.to_datetime(df['GAME_DATE_EST'])
    df['GAME_DATE_EST'] = df['GAME_DATE_EST'].dt.strftime('%Y-%m-%d')
    df['GAME_DATE_EST'] = pd.to_datetime(df['GAME_DATE_EST'])

    return df


def combine_home_visitor(df: pd.DataFrame) -> pd.DataFrame:

    home_df = df[df['HOME'] == 1]
    visitor_df = df[df['HOME'] == 0]

    home_df = home_df.drop(columns='HOME')
    visitor_df = visitor_df.drop(columns='HOME')

    visitor_df = visitor_df.drop(columns=['HOME_TEAM_WINS', 'GAME_DATE_EST'])

    home_df = home_df.rename(columns={'TEAM_ID': 'HOME_TEAM_ID'})
    visitor_df = visitor_df.rename(columns={'TEAM_ID': 'VISITOR_TEAM_ID'})

    df = pd.merge(home_df, visitor_df, how="left", on=["GAME_ID"], suffixes=('_home', '_away'))

    game_id = df['GAME_ID'].iloc[0]
    season = game_id[3:5]
    season = str(20) + season
    df['SEASON'] = season

    # convert all object columns to int64 to match hopsworks
    for field in df.select_dtypes(include=['object']).columns.tolist():
        df[field] = df[field].astype('int64')

    return df


def get_todays_matchups(api_key: str, driver: webdriver) -> tuple[list, list]:

    NBA_SCHEDULE = "https://www.nba.com/schedule"

    if api_key == "":  # if no api key, then use selenium
        driver.get(NBA_SCHEDULE)
        time.sleep(10)
        source = soup(driver.page_source, 'html.parser')
    else:
        client = ScrapingAntClient(token=api_key)
        result = client.general_request(NBA_SCHEDULE)
        source = soup(result.content, 'html.parser')

    CLASS_GAMES_PER_DAY = "ScheduleDay_sdGames__NGdO5"
    CLASS_DAY = "ScheduleDay_sdDay__3s2Xt"
    div_games = source.find('div', {
        'class': CLASS_GAMES_PER_DAY})
    div_game_day = source.find('h4', {'class': CLASS_DAY})
    today = datetime.today().strftime('%A, %B %d')[
            :3]
    todays_games = None

    while div_games:
        print(div_game_day.text[:3])
        if today == div_game_day.text[:3]:
            todays_games = div_games
            break
        else:
            div_games = div_games.find_next('div', {'class': CLASS_GAMES_PER_DAY})
            div_game_day = div_game_day.find_next('h4', {'class': CLASS_DAY})

    if todays_games is None:
        # no games today
        return None, None

    CLASS_ID = "Anchor_anchor__cSc3P Link_styled__okbXW"
    links = todays_games.find_all('a', {'class': CLASS_ID})
    teams_list = [i.get("href") for i in links]

    team_count = len(teams_list)
    matchups = []
    for i in range(0, team_count, 2):
        visitor_id = teams_list[i].partition("team/")[2].partition("/")[0]  # extract team id from text
        home_id = teams_list[i + 1].partition("team/")[2].partition("/")[0]
        matchups.append([visitor_id, home_id])

    CLASS_ID = "Anchor_anchor__cSc3P TabLink_link__f_15h"
    links = todays_games.find_all('a', {'class': CLASS_ID})
    links = [i for i in links if "PREVIEW" in i]
    game_id_list = [i.get("href") for i in links]

    games = []
    for game in game_id_list:
        game_id = game.partition("-00")[2].partition("?")[0]  # extract team id from text for link
        if len(game_id) > 0:
            games.append(game_id)

    return matchups, games
