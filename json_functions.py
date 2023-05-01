import json
from youtube_api import get_channel_videos

def open_json(filepath):
    with open(filepath, 'r') as file:
        jsonFile = json.load(file)
    return jsonFile

def add_vids_to_json(channels, yt_api, max_results_per_channel, json_file):
    new_videos = 0

    for channel in channels:
        print(f"Fetching videos from {channel['name']}...")
        videos = get_channel_videos(yt_api, channel['id'], max_results_per_channel)

        for video in videos:
            new_video_id = video['id']['videoId']
            channel_name = channel['name']

            if channel_name not in json_file or json_file[channel_name]['video_id'] != new_video_id:
                json_file[channel_name] = {
                    "video_id": new_video_id,
                    "is_new": True
                }
                new_videos += 1
            else:
                json_file[channel_name]["is_new"] = False

    if new_videos == len(channels):
        print("Both video IDs are new.")
        return True
    else:
        print("One or both video IDs are not new.")
        return False

    print("Done")


def write_to_json(filename, json_file):
    with open(filename, 'w') as file:
        json.dump(json_file, file, indent=4)