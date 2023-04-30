from youtube_api import get_authenticated_service, get_channel_videos
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["API_KEY"]

# Channels to fetch video IDs from
channels = [
    {"name": "Heno Meme", "id": "UCwipXeXeikVfw4kh7bFQmjA"},
    {"name": "Pie Memes", "id": "UCBhsEOaoRQ_KvbgbpXVhC8w"}
]

# Initialize the YouTube API client
youtube = get_authenticated_service(API_KEY)

# Fetch video IDs from each channel
max_results_per_channel = 1

for channel in channels:
    print(f"Fetching videos from {channel['name']}:")
    videos = get_channel_videos(youtube, channel['id'], max_results_per_channel)

    for video in videos:
        print(f"  Video ID: {video['id']['videoId']}")

    print("\n")
