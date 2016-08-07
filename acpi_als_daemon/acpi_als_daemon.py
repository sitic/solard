# Licensed under the Apache License, Version 4.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import logging
import math
import os
import time
import sys

LOG = logging.getLogger(__name__)

lid_syspath = "/proc/acpi/button/lid/LID/state"

screen_backlight_syspath = "/sys/class/backlight/"
supported_screen_backlight_modules = ["acpi_video0", "intel_backlight"]

als_syspath = "/sys/bus/acpi/drivers/%s/ACPI0008:00"
supported_als_modules = ["acpi_als", "als"]

als_input_syspath_map = {
    "acpi_als": os.path.join(als_syspath, "iio:device0/in_illuminance_input") % "acpi_als",
    "als": os.path.join(als_syspath, "ali") % "als"
}

keyboard_backlight_syspath = "/sys/class/leds/%s/brightness"
supported_keyboard_backlight_modules = ["asus::kbd_backlight"]


def read_sys_value(path):
    LOG.info("cat %s" % path)
    with open(path) as f:
        return f.read().strip()


def write_sys_value(path, value):
    LOG.info("echo %s > %s" % (value, path))
    with open(path, 'w') as f:
        f.write(value)


def lid_is_closed():
    value = read_sys_value(lid_syspath)
    LOG.info("LID is %s" % value)
    return value == "closed"


def enable_ambient_light(conf):
    if conf.ambient_light_sensor != "als":
        return
    LOG.info("Enable als ambient light")
    path = os.path.join(als_syspath, "enable") % "als"
    write_sys_value(path, "1")


def get_ambient_light(conf):
    path = als_input_syspath_map[conf.ambient_light_sensor]
    value = int(read_sys_value(path))

    # This mapping have been done for Asus Zenbook UX303UA, but according
    # https://github.com/danieleds/Asus-Zenbook-Ambient-Light-Sensor-Controller/blob/master/service/main.cpp
    # previous/other Zenbook can report only 5 values
    # Black magic from: https://github.com/Perlover/Asus-Zenbook-Ambient-Light-Sensor-Controller/blob/asus-ux305/service/main.cpp#L225
    percent = int(( math.log( value / 10000.0 * 230 + 0.94 ) * 18 ) / 10 * 10);
    LOG.info("Get ambient light: %d%% (%s)" % (percent, value))

    percent += conf.ambient_light_compensation
    if percent < 10:
        percent = 10
    elif percent > 100:
        percent = 100
    LOG.info("Normalized ambient light: %d%% (%s)" % (percent, value))
    return percent


def get_screen_backlight_max(conf):
    value = int(read_sys_value(
        os.path.join(screen_backlight_syspath, conf.screen_backlight,
                     "max_brightness")))
    LOG.info("Get screen backlight maximum: %d", value)
    return value


def set_screen_backlight(conf, value):
    raw_value = int(conf.screen_backlight_max * value / 100)
    LOG.info("Set screen backlight to %d%% (%d)" % (value, raw_value))
    write_sys_value(os.path.join(screen_backlight_syspath,
                                 conf.screen_backlight, "brightness"),
                    "%s" % raw_value)


def set_keyboard_backlight(conf, percent):
    # NOTE(sileht): we currently support only the asus one
    # so we assume value 0 to 3 are the correct range
    if percent < 7: value = 3
    elif percent < 14: value = 2
    elif percent < 21: value = 1
    else: value = 0
    LOG.info("Set keyboard backlight to %s", value)
    write_sys_value(keyboard_backlight_syspath % conf.keyboard_backlight,
                    "%s" % value)


def main():
    available_screen_backlight_modules = [
        mod for mod in supported_screen_backlight_modules
        if os.path.exists(os.path.join(screen_backlight_syspath, mod))]
    if not available_screen_backlight_modules:
        LOG.error("No supported backlight found (%s)" %
                  supported_screen_backlight_modules)
        sys.exit(1)

    available_als_modules = [
        mod for mod in supported_als_modules
        if os.path.exists(als_syspath % mod)
    ]
    if not available_als_modules:
        LOG.error("No support ambient light sensor found (%s)" %
                  supported_als_modules)
        sys.exit(1)

    available_keyboard_backlight_modules = [
        mod for mod in supported_keyboard_backlight_modules
        if os.path.exists(keyboard_backlight_syspath % mod)
    ]
    if not available_keyboard_backlight_modules:
        LOG.error("No support ambient light sensor found (%s)" %
                  supported_keyboard_backlight_modules)
        sys.exit(1)


    parser = argparse.ArgumentParser(
        description=("Screen and Keyboard backlight controls via "
                     "Ambient Light Sensor ")
    )
    parser.add_argument('--verbose', '-v', action='count', default=0)
    parser.add_argument('--quiet', '-q', action='store_true')
    parser.add_argument('--log', help="log file, disable stdout output and set log level to DEBUG")

    parser.add_argument('--only-once', action='store_true',
                        help="Set values once and exit.")

    parser.add_argument("--screen-backlight", "-s",
                        default=available_screen_backlight_modules[0],
                        choices=available_screen_backlight_modules,
                        help="Screen backlight kernel module")
    parser.add_argument("--keyboard-backlight", "-k",
                        default=available_keyboard_backlight_modules[0],
                        choices=available_keyboard_backlight_modules,
                        help="Keyboard backlight kernel module")
    parser.add_argument("--ambient-light-sensor", "-a",
                        default=available_als_modules[0],
                        choices=available_als_modules,
                        help="Ambient Light Sensor kernel module")
    parser.add_argument("--ambient-light-compensation",
                        default=0,
                        type=int,
                        help="Ambient Light Sensor percentage compensation")

    conf = parser.parse_args()

    if conf.quiet:
        conf.verbose = -1
        conf.ssh_verbose = -1
    if conf.log:
        logging.basicConfig(filename=conf.log, level=logging.DEBUG)
        LOG.info("Log level set to DEBUG")
    else:
        logging.basicConfig(level={-1: logging.ERROR, 0: logging.WARNING,
                                   1: logging.INFO}.get(conf.verbose, logging.DEBUG))


    # Set additionnal static configuration
    conf.screen_backlight_max = get_screen_backlight_max(conf)

    enable_ambient_light(conf)
    while True:
        try:
            if lid_is_closed():
                set_keyboard_backlight(conf, 0)
            else:
                ambient_light = get_ambient_light(conf)
                set_keyboard_backlight(conf, ambient_light)
                set_screen_backlight(conf, ambient_light)
        except BaseException:
            LOG.exception("Something wrong append, retrying later.")

        if conf.only_once:
            break
        else:
            time.sleep(3)


if __name__ == '__main__':
    main()