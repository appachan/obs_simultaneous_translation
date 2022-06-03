#!/usr/bin/env python3

import argparse
from getpass import getpass
import queue
import sounddevice as sd
import vosk
import sys
import json
from obswebsocket import obsws, requests
import argostranslate.package, argostranslate.translate

q = queue.Queue()

def int_or_str(text):
    """Helper function for argument parsing."""
    try:
        return int(text)
    except ValueError:
        return text

def callback(indata, frames, time, status):
    """This is called (from a separate thread) for each audio block."""
    if status:
        print(status, file=sys.stderr)
    q.put(bytes(indata))

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument(
    '-l', '--list-devices', action='store_true',
    help='show list of audio devices and exit')
args, remaining = parser.parse_known_args()
if args.list_devices:
    print(sd.query_devices())
    parser.exit(0)
parser = argparse.ArgumentParser(
    description=__doc__,
    formatter_class=argparse.RawDescriptionHelpFormatter,
    parents=[parser])
parser.add_argument(
    '-f', '--filename', type=str, metavar='FILENAME',
    help='audio file to store recording to')
parser.add_argument(
    '-d', '--device', type=int_or_str,
    help='input device (numeric ID or substring)')
parser.add_argument(
    '-r', '--samplerate', type=int, help='sampling rate')
args = parser.parse_args(remaining)

password = getpass('your obs-websocket password: ')

from_code = "ja"
to_code = "en"

# set-up translation
argostranslate.package.update_package_index()
available_packages = argostranslate.package.get_available_packages()
available_package = list(
    filter(
        lambda x: x.from_code == from_code and x.to_code == to_code, available_packages
    )
)[0]
download_path = available_package.download()
argostranslate.package.install_from_path(download_path)
installed_languages = argostranslate.translate.get_installed_languages()
from_lang = list(filter(
	lambda x: x.code == from_code,
	installed_languages))[0]
to_lang = list(filter(
	lambda x: x.code == to_code,
	installed_languages))[0]
translation = from_lang.get_translation(to_lang)

host = "localhost"
port = 4444
ws = obsws(host, port, password)


try:
    if args.samplerate is None:
        device_info = sd.query_devices(args.device, 'input')
        # soundfile expects an int, sounddevice provides a float:
        args.samplerate = int(device_info['default_samplerate'])

    model = vosk.Model("model")

    if args.filename:
        dump_fn = open(args.filename, "wb")
    else:
        dump_fn = None

    ws.connect()
    caption_source = "obs_simultaneous_translation"

    with sd.RawInputStream(samplerate=args.samplerate, blocksize = 4000, device=args.device, dtype='int16',
                            channels=1, callback=callback):
            print('#' * 80)
            print('Press Ctrl+C to stop the recording')
            print('#' * 80)

            rec = vosk.KaldiRecognizer(model, args.samplerate)
            while True:
                data = q.get()
                if rec.AcceptWaveform(data):
                    recResult = json.loads(rec.Result())["text"]
                    print("fix: " + recResult)
                    translatedText = translation.translate(recResult.replace(" ", ""))
                    res = ws.call(
                        requests.SetTextGDIPlusProperties(
                            source=caption_source,
                            chatlog=True,
                            chatlog_lines=2,
                            text='\n'.join([recResult, translatedText])
                        )
                    )
                else:
                    pass
                if dump_fn is not None:
                    dump_fn.write(data)

except KeyboardInterrupt:
    print('\nDone')
    ws.disconnect()
    parser.exit(0)
except Exception as e:
    ws.disconnect()
    parser.exit(type(e).__name__ + ': ' + str(e))
