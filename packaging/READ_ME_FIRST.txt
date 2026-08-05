auto_sub - Arabic subtitles for your videos
===========================================

HOW TO START
------------
1. Unzip this folder somewhere easy, like your Desktop.
   (Do not run it from inside the zip. Unzip it first.)
2. Double-click  auto_sub.exe
3. Windows may show a blue box saying "Windows protected your PC".
   Click "More info", then "Run anyway". This happens because the app
   is not signed. It is safe to allow.

HOW TO USE IT
-------------
The buttons at the top are numbered 1, 2, 3, 4. The blue one is the
one to press next. Just follow the blue button.

1. Open video   - pick your video file, or drag it into the window.

2. Transcribe   - the app listens to the video and writes down the English.

                  THE VERY FIRST TIME, this downloads about 1.6 GB.
                  It can take 10-30 minutes on a slow connection.
                  The bar at the bottom right shows how far along it is.
                  It only happens once, ever. After that it is instant.

                  Transcribing itself takes a few minutes per minute of
                  video. This is normal. Let it run.

3. Translate    - a window opens with English on the left, Arabic on
                  the right.
                  - Press "Copy prompt".
                  - Open Claude or ChatGPT in your browser, paste it,
                    press enter.
                  - Copy the Arabic it gives you.
                  - Paste it into the big box in the app, then press
                    "Fill Arabic column from paste".
                  - Check the Arabic lines line up with the English ones.
                    You can click any cell and fix it by hand.
                  - Press OK.

4. Burn & Export - choose where to save, pick the shape:
                  - "Source" keeps the video the way it is.
                  - "Vertical 9:16" crops it for TikTok / Reels / Shorts
                    and follows the speaker's face.
                  Then wait. The finished video is saved where you chose.

The panel on the right changes how the subtitles look - font, size,
colour, background box, position. Change it before you press Burn.

IF SOMETHING GOES WRONG
-----------------------
There is a log file. Send it to Ahmad and he can see what happened:

  Press Windows key + R, paste this in, press Enter:
  %LOCALAPPDATA%\auto_sub\auto_sub.log

Common things:
- "It looks frozen on step 2"  -> it is downloading or transcribing.
  Look at the bar at the bottom right. Give it time.
- "The subtitles are in English" -> step 3 was cancelled, or nothing was
  pasted in the Arabic column. Press 3 again.
- Nothing happens on double-click -> make sure you unzipped the folder,
  and that auto_sub.exe is still sitting next to all the other files.
  Do not move auto_sub.exe out on its own.

WHAT IT NEEDS
-------------
Nothing. No installing, no accounts, no keys, no internet after the
first download. Everything runs on your own computer.
