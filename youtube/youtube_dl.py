import subprocess

def download_video(url):
    subprocess.call(["node", "node_scripts/downloader.js", url])
