const fs = require("fs");
const ytdl = require("ytdl-core");

const args = process.argv.slice(2);
const url = args[0];

const iTag = 22;
const video = ytdl(url, {
  filter: function (format) {
    return format.itag === iTag;
  },
});
video.pipe(fs.createWriteStream("video.mp4"));
