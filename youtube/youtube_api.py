import google_auth_httplib2
import google_auth_oauthlib.flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

def get_authenticated_service(api_key):
    return build('youtube', 'v3', developerKey=api_key)

def get_channel_videos(service, channel_id, max_results):
    try:
        search_request = service.search().list(
            channelId=channel_id,
            type='video',
            part='id',
            maxResults=max_results,
            order='date'
        )
        response = search_request.execute()
        return response['items']
    except HttpError as e:
        print(f"An HTTP error {e.resp.status} occurred: {e.content}")
        return []

## used to test youtube_api.py
# if __name__ == "__main__":
#     # Replace this with your YouTube API key
#     API_KEY = "YOUR_API_KEY"

#     # Channels to fetch video IDs from (replace these with your desired channels)
#     channels = [
#         {"name": "Channel1", "id": "CHANNEL_ID_1"},
#         {"name": "Channel2", "id": "CHANNEL_ID_2"}
#     ]

#     # Initialize the YouTube API client
#     youtube = get_authenticated_service(API_KEY)

#     # Fetch video IDs from each channel
#     max_results_per_channel = 5

#     for channel in channels:
#         print(f"Fetching videos from {channel['name']}:")
#         videos = get_channel_videos(youtube, channel['id'], max_results_per_channel)

#         for video in videos:
#             print(f"  Video ID: {video['id']['videoId']}")

#         print("\n")
