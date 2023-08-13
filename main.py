from youtube.youtube_api import *
from utils.json_functions import *
import os
from dotenv import load_dotenv

load_dotenv()

# Reading the JSON file
curVids = open_json("assets/curVids.json")


# Getting API Key from virtual environment
API_KEY = os.environ["API_KEY"]

# Channels to fetch video IDs from
channels = [
    {"name": "Heno Meme", "id": os.environ["channel_1"]},
    {"name": "Pie Memes", "id": os.environ["channel_2"]}
]

# Initialize the YouTube API client
youtube = get_authenticated_service(API_KEY)

# Fetch video IDs from each channel
max_results_per_channel = 1

result = add_vids_to_json(channels, youtube, max_results_per_channel, curVids)

# Writing the updated data back to the JSON file
write_to_json("assets/curVids.json", curVids)

if(result):
    url = "https://www.youtube.com/watch?v="
    for channels in curVids:
        # TODO: Implement video downloads
        continue