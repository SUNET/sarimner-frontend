#!/usr/bin/python3
#
# Copyright 2018 SUNET. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are
# permitted provided that the following conditions are met:
#
#    1. Redistributions of source code must retain the above copyright notice, this list of
#       conditions and the following disclaimer.
#
#    2. Redistributions in binary form must reproduce the above copyright notice, this list
#       of conditions and the following disclaimer in the documentation and/or other materials
#       provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY SUNET ``AS IS'' AND ANY EXPRESS OR IMPLIED
# WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND
# FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL SUNET OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
# ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
# ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# The views and conclusions contained in the software and documentation are those of the
# authors and should not be interpreted as representing official policies, either expressed
# or implied, of SUNET.
#
# Author : Fredrik Thulin <fredrik@thulin.net>
#
"""
Monitor the 'announce' files for all instances and propagate changes of them to exabgp.

Install this script as /etc/bgp/monitor and configure exabgp with this:

   process watch-service {
        run /etc/bgp/monitor;
        encoder text;
   }

If exabgp runs in a docker container, make sure to volume mount the monitor_dir
(default /opt/frontend/monitor) into that container.
"""
import argparse
import asyncio
import logging
import logging.handlers
import os
import random
from dataclasses import dataclass, field
from typing import Dict

import sys
import time
from pyinotify import AsyncioNotifier, Event, EventsCodes, ProcessEvent, WatchManager

_defaults = {'syslog': True,
             'debug': False,
             'monitor_dir': '/opt/frontend/monitor',
             'timeout': 60,  # TODO: Re-implement the timeout functionality after moving to asyncio!
             }


def parse_args(defaults):
    parser = argparse.ArgumentParser(description = 'exabgp monitor for SUNET frontends',
                                     add_help = True,
                                     formatter_class = argparse.ArgumentDefaultsHelpFormatter,
    )

    # Optional arguments
    parser.add_argument('--monitor_dir',
                        dest = 'monitor_dir',
                        metavar = 'DIR', type = str,
                        default = defaults['monitor_dir'],
                        help = 'Base directory to monitor',
    )
    parser.add_argument('--timeout',
                        dest = 'timeout',
                        metavar = 'SECONDS', type = int,
                        default = defaults['timeout'],
                        help = 'Re-check files at least this often',
    )
    parser.add_argument('--debug',
                        dest = 'debug',
                        action = 'store_true', default = defaults['debug'],
                        help = 'Enable debug operation',
    )
    parser.add_argument('--syslog',
                        dest = 'syslog',
                        action = 'store_true', default = defaults['syslog'],
                        help = 'Enable syslog output',
    )
    args = parser.parse_args()
    return args


def init_logger(myname, args):
    # This is the root log level
    level = logging.INFO
    if args.debug:
        level = logging.DEBUG
    logging.basicConfig(level = level, stream = sys.stderr,
                        format='%(asctime)s: %(name)s: %(levelname)s %(message)s')
    logger = logging.getLogger(myname)
    # If stderr is not a TTY, change the log level of the StreamHandler (stream = sys.stderr above) to WARNING
    if not sys.stderr.isatty() and not args.debug:
        for this_h in logging.getLogger('').handlers:
            this_h.setLevel(logging.WARNING)
    if args.syslog:
        syslog_h = logging.handlers.SysLogHandler()
        formatter = logging.Formatter('%(name)s: %(levelname)s %(message)s')
        syslog_h.setFormatter(formatter)
        logger.addHandler(syslog_h)
    return logger


class InstanceDir(object):

    def __init__(self, dir, timeout, logger):
        self.dir = dir
        self.name = dir.split('/')[-1]
        self._logger = logger
        self._timeout_ts = time.time() + timeout + (random.random() * 5)  # fuzz poll timeouts a bit
        self._timeout = timeout
        self.announce_fn = os.path.join(self.dir, 'announce')
        self._contents = None
        if os.path.isfile(self.announce_fn):
            self.reload()

    def __repr__(self):
        return '<{} instance at {:#x}: fn={})>'.format(self.__class__.__name__, id(self), self.announce_fn)

    def __str__(self):
        return '<{}({})>'.format(self.__class__.__name__, self.name)

    def reload(self):
        """
        Reload the announce file.

        :return: True if file contents were updated, False otherwise. None on errors.
        """
        #self._logger.debug('{}: Loading {}'.format(self, self.announce_fn))
        try:
            with open(self.announce_fn) as fd:
                # discard lines not starting with announce/withdraw
                new = []
                for this in fd.readlines():
                    if this.startswith('announce ') or this.startswith('withdraw '):
                        new += [this]
                    else:
                        self._logger.warning('{}: Discarded unknown command: {!r}'.format(self, this))
        except IOError as exc:
            self._logger.warning('Error reading announce file {}: {}'.format(self.announce_fn, exc))
            return None

        if new != self._contents:
            if new:
                parts = new[0].split(' ')
                if parts[0] in ['announce', 'withdraw']:
                    self._logger.info('{}: Announcement updated (first command: {})'.format(
                        self, ' '.join(new[0].split(' ')[0:3])))
                else:
                    # Since only announce and withdraw lines are kept above, we only end up here if the
                    # net result was an empty file. Don't want to crash though.
                    self._logger.info('{}: Announcement updated'.format(self))
                for line in new:
                    self._logger.debug('  cmd: {!r}'.format(line))
                    sys.stdout.write(line)
                sys.stdout.flush()
            self._contents = new
            return True
        #else:
        #    self._logger.debug('{}: No changes'.format(self))
        return False

    def withdraw(self):
        """
        Withdraw routes previously loaded from the announce file. Typically called when
        the file disappears.

        :return:
        """
        self._logger.info('{}: Withdrawing any previous announcements'.format(self))
        new = []
        for line in self._contents:
            if line.startswith('announce '):
                line = 'withdraw ' + line[9:]
                self._logger.debug('  cmd: {!r}'.format(line))
                sys.stdout.write(line)
                new += [line]
        sys.stdout.flush()
        self._contents = new

    def poll(self, now):
        """
        Periodic poll to see if the file contents changed without this script getting
        notified about it somehow.

        Maybe the inotify mechanism works 100%, but better make double sure that all
        updates are propagated to the router infrastructure.

        :param now: Current timestamp
        :return: None
        """
        if now > self._timeout_ts:
            inc = self._timeout + random.random() - 0.5
            self._logger.debug('{}: Polling for changes (next timeout in {:.2f} seconds)'.format(self, inc))
            self._timeout_ts = now + inc
            if self.reload():
                self._logger.warning('{}: Scheduled poll detected unexpected changes'.format(self))

@dataclass
class State:
    dirs: Dict[str, InstanceDir] = field(default_factory=dict)


class AnnounceEvent(ProcessEvent):

    def __init__(self, args, logger, state: State):
        super().__init__()
        self._args = args
        self._logger = logger
        self._state = state

    def process_default(self, event: Event):
        if not event.pathname.endswith('/announce'):
            self._logger.debug(f'Not an announce file: {event.pathname}')
            return
        if event.maskname == 'IN_MOVED_TO':
            _dir = os.path.dirname(event.pathname)
            if _dir in self._state.dirs:
                self._state.dirs[_dir].reload()
            else:
                _timeout = self._args.timeout + (random.random() * 5) - 2.5  # spread polling intervals
                this = InstanceDir(_dir, _timeout, self._logger)
                self._state.dirs[_dir] = this
                logger.info(f'Added instance {this}')
        elif event.maskname == 'DELETE':
            _dir = os.path.dirname(event.pathname)
            if _dir in self._state.dirs:
                self._state.dirs[_dir].withdraw()
                this = self._state.dirs.pop(_dir)
                logger.info(f'Removed instance {this}')
        else:
            self._logger.warning(f'Unhandled announce event: {event}')


def main(args, logger):
    wm = WatchManager()
    loop = asyncio.get_event_loop()
    mask = (EventsCodes.ALL_FLAGS['IN_MOVED_TO'] |
            EventsCodes.ALL_FLAGS['IN_CREATE'] |
            EventsCodes.ALL_FLAGS['IN_DELETE']
            )

    state = State()
    # Add a monitor for each instance in the top level directory
    for this in os.listdir(args.monitor_dir):
        dir = os.path.join(args.monitor_dir, this)
        if os.path.isdir(dir):
            _timeout = args.timeout + (random.random() * 5) - 2.5  # spread polling intervals
            this = InstanceDir(dir, _timeout, logger)
            state.dirs[dir] = this
            logger.debug(f'Startup added directory {this}')

    notifier = AsyncioNotifier(wm, loop, default_proc_fun=AnnounceEvent(args, logger, state))
    wm.add_watch(args.monitor_dir, mask, rec=True, auto_add=True)
    loop.run_forever()
    notifier.stop()
    return False


if __name__ == '__main__':
    try:
        progname = os.path.basename(sys.argv[0])
        args = parse_args(_defaults)
        logger = init_logger(progname, args)
        res = main(args, logger)
        if res is True:
            sys.exit(0)
        if res is False:
            sys.exit(1)
        sys.exit(int(res))
    except KeyboardInterrupt:
        sys.exit(0)
