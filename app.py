%%writefile app.py
import os
import requests
from datetime import datetime, timezone
import pytz
import pandas as pd
import streamlit as st

# Configure Page for Mobile/Desktop layout
st.set_page_config(page_title="NFL Confidence Picks", page_icon="🏈", layout="wide")

# Securely fetch API key from environment variables (or Streamlit Secrets on cloud)
API_KEY = os.getenv("ODDS_API_KEY", "34e82928d6db02ae9cefba7d21068338")
SPORT = "americanfootball_nfl"
REGIONS = "us"
MARKETS = "h2h"
ODDS_FORMAT = "decimal"
TARGET_TIMEZONE = "America/New_York"

def get_nfl_odds(api_key: str):
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"
    params = {
        "apiKey": api_key,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": ODDS_FORMAT,
    }
    response = requests.get(url, params=params)
    if response.status_code != 200:
        raise ValueError(f"API Error ({response.status_code}): {response.text}")
    return response.json()

def calculate_no_vig_probabilities(outcomes: list) -> dict:
    raw_probs = {}
    for outcome in outcomes:
        team = outcome["name"]
        price = outcome["price"]
        raw_probs[team] = 1.0 / price
    total_prob = sum(raw_probs.values())
    return {team: prob / total_prob for team, prob in raw_probs.items()}

def process_slate(games: list) -> list:
    sorted_games = sorted(games, key=lambda x: x.get("commence_time", ""))
    results = []
    assigned_teams = set()

    for game in sorted_games:
        home_team = game["home_team"]
        away_team = game["away_team"]
        if home_team in assigned_teams or away_team in assigned_teams:
            continue

        bookmakers = game.get("bookmakers", [])
        if not bookmakers: 
            continue

        team_probs = {home_team: [], away_team: []}
        for book in bookmakers:
            for market in book.get("markets", []):
                if market["key"] == "h2h" and len(market["outcomes"]) == 2:
                    no_vig = calculate_no_vig_probabilities(market["outcomes"])
                    for team, prob in no_vig.items():
                        if team in team_probs:
                            team_probs[team].append(prob)

        if not team_probs[home_team] or not team_probs[away_team]:
            continue

        home_prob = sum(team_probs[home_team]) / len(team_probs[home_team])
        away_prob = sum(team_probs[away_team]) / len(team_probs[away_team])

        if "San Francisco 49ers" in (home_team, away_team):
            pick = "San Francisco 49ers"
            pick_prob = home_prob if home_team == "San Francisco 49ers" else away_prob
            opponent = away_team if home_team == "San Francisco 49ers" else home_team
            opp_prob = away_prob if home_team == "San Francisco 49ers" else home_prob
        elif home_prob >= away_prob:
            pick = home_team
            pick_prob = home_prob
            opponent = away_team
            opp_prob = away_prob
        else:
            pick = away_team
            pick_prob = away_prob
            opponent = home_team
            opp_prob = home_prob

        results.append({
            "matchup": f"{away_team} @ {home_team}",
            "pick": pick,
            "pick_prob": pick_prob,
            "opponent": opponent,
            "opp_prob": opp_prob,
            "num_books": len(team_probs[home_team]),
            "commence_time": game.get("commence_time"),
        })
        assigned_teams.add(home_team)
        assigned_teams.add(away_team)
    return results

st.title("🏈 NFL Confidence Picks")
st.write("Calculates optimal confidence rankings using real-time consensus moneyline odds (with vig removed).")

try:
    slate = get_nfl_odds(API_KEY)
    ranked_slate = process_slate(slate)

    if ranked_slate:
        local_tz = pytz.timezone(TARGET_TIMEZONE)
        current_time_utc = datetime.now(timezone.utc)
        current_time_local = current_time_utc.astimezone(local_tz)

        st.caption(f"Last updated: {current_time_local.strftime('%Y-%m-%d %I:%M %p %Z')}")

        current_week_games = []
        next_week_games = []
        threshold_date = datetime(2026, 10, 14, tzinfo=timezone.utc)

        for game in ranked_slate:
            commence_str = game["commence_time"]
            try:
                commence_time_utc = datetime.strptime(commence_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            except ValueError:
                commence_time_utc = current_time_utc

            if commence_time_utc < threshold_date:
                current_week_games.append(game)
            else:
                next_week_games.append(game)

        # --- Current Week MNF Game ---
        if current_week_games:
            st.subheader("📺 Tonight's Game (Week 5 Closing)")
            for game in current_week_games:
                st.metric(
                    label=f"{game['matchup']} (Kickoff: {datetime.strptime(game['commence_time'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).astimezone(local_tz).strftime('%I:%M %p')})",
                    value=f"Pick: {game['pick']}",
                    delta=f"{game['pick_prob']*100:.1f}% Win Probability"
                )

        # --- Next Week Games (Week 6) ---
        if next_week_games:
            st.subheader("📅 Next Week's Slate (Week 6 Confidence Pool)")
            total_next_week = len(next_week_games)
            next_week_games.sort(key=lambda x: x["pick_prob"], reverse=True)

            available_points = list(range(1, total_next_week + 1))[::-1]
            table_rows = []
            
            for idx, game in enumerate(next_week_games):
                pts = available_points[idx]
                p = game["pick_prob"]
                commence_time_utc = datetime.strptime(game["commence_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                commence_time_local = commence_time_utc.astimezone(local_tz)

                table_rows.append({
                    "Points": pts,
                    "Your Pick": game["pick"],
                    "Win Prob": f"{p*100:.1f}%",
                    "Matchup": game["matchup"],
                    "Kickoff (Local)": commence_time_local.strftime('%m/%d %I:%M %p'),
                    "Expected Pts": f"{pts * p:.2f}",
                    "Books": game["num_books"]
                })
            
            df = pd.DataFrame(table_rows)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No Week 6 games released by the API yet.")

    else:
        st.warning("No active games returned by API.")
except Exception as e:
    st.error(f"Error fetching data: {e}")
