import os
import time
import re
import logging
import threading
import subprocess
import functools

import sublime, sublime_plugin  
from telnetlib import Telnet

LOG = logging.getLogger(__name__)

try:
    from Queue import Queue, Empty
except ImportError:
    from queue import Queue, Empty  # python 3.x

_settings = {
    'host'      : '127.0.0.1',
    'py_port'   : 7002
}

HISTFILE = "~/.mayaHistory"
PANELNAME = "mayaHistory"
WATCHING = False
CONTINUE = False
BUFFSIZE = 1000 # Lines
MSGQUEUE = None
PANELTITLE = "LOG: Maya"

MAYASHELF = '''import os
from pymel.core import *

mayaHistoryPath = "~/.mayaHistory"
mayaHistoryPath = os.path.expanduser(mayaHistoryPath)

# Reset the history file
try:
    f = open(mayaHistoryPath, 'w')
    f.write("")
    f.close()
except:
    print "Unable to clear maya history file"

scriptEditorInfo(e=True, wh=True)
scriptEditorInfo(e=True, hfn=mayaHistoryPath)

try:
    result = cmds.commandPort(name=":7002", sourceType="python", echoOutput=True)
    print "Command Port started on 7002"
except:
    print "Unable to start Command Port on 7002. It might be already running"
'''

class WatchMayaHistoryCommand(sublime_plugin.TextCommand):
    ''' Start watching maya history, and display output panel '''
    proc = None

    def watchMayaHistory(self):
        ''' Watch tail process, and queue new lines '''
        global WATCHING
        while True:
            if CONTINUE:
                line = self.proc.stdout.readline()
                MSGQUEUE.put(line)
            else:
                MSGQUEUE.put("# Stopped watching maya: User Cancelled")
                MSGQUEUE.put("#STOP#")
                WATCHING = False
                break

    def postMayaHistory(self):
        ''' Send maya history to update '''
        while WATCHING:
            newTxt = ""
            while True:
                try:
                    newTxt += MSGQUEUE.get_nowait()
                except Empty:
                    # No more lines in queue
                    break
            if len(newTxt):
                sublime.set_timeout(functools.partial(self.update, newTxt), 0)
            time.sleep(.1)

    def update(self, output):
        ''' Add the lines to the output panel, run on main thread '''
        if len(output):
            panel_edit = self.panel.begin_edit()

            # Insert the new output
            self.panel.set_read_only(False)
            self.panel.insert(panel_edit, self.panel.size(), output)

            # Limit the buffer size
            lines = self.panel.lines(sublime.Region(0, self.panel.size()))
            if len(lines) > BUFFSIZE:
                reg = sublime.Region(lines[0].begin(), lines[:-BUFFSIZE][-1].end())
                self.panel.erase(panel_edit, reg)

            self.panel.end_edit(panel_edit)
            self.panel.set_read_only(True)
            sublime.set_timeout(self.scrollView, 0)

    def scrollView(self):
        ''' Scroll separately, or view might not scroll to end '''
        self.panel.show(self.panel.size())

    def run(self, edit):
        ''' Main run method '''
        global CONTINUE
        global WATCHING
        global MSGQUEUE

        win = sublime.active_window()
        win.run_command("show_maya_history")
        if not WATCHING:
            matchingViews = filter(lambda v: v.name() == PANELTITLE, sublime.active_window().views())
            self.panel = matchingViews[0] if len(matchingViews) else None
            self.panel.set_read_only(False)

            # Clear the panel
            panel_edit = self.panel.begin_edit()
            self.panel.erase(panel_edit, sublime.Region(0, self.panel.size()))
            
            self.panel.end_edit(panel_edit)
            self.panel.show(self.panel.size())

            # Start the tail process
            cmd = "tail -n 0 -f \"{0}\"".format(os.path.expanduser(HISTFILE))
            self.proc = INSTANCE = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=-1)
            
            # Start the threads
            CONTINUE = True
            WATCHING = True
            MSGQUEUE = Queue()
            watch = threading.Thread(target=self.watchMayaHistory)
            watch.start()

            post = threading.Thread(target=self.postMayaHistory)
            post.start()

            self.panel.set_read_only(True)

class ToggleMayaHistoryCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        ''' Toggle the maya history panel'''
        win = sublime.active_window()
        matchingViews = filter(lambda v: v.name().strip() == PANELTITLE, win.views())
        self.panel = matchingViews[0] if len(matchingViews) else None
        if self.panel is not None:
            win.run_command("close_maya_history")
        else:
            win.run_command("show_maya_history")

class ShowMayaHistoryCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        ''' Show the maya history view '''
        win = sublime.active_window()
        matchingViews = filter(lambda v: v.name() == PANELTITLE, win.views())
        self.panel = matchingViews[0] if len(matchingViews) else None
        if self.panel is None:
            activeView = win.active_view()
            win.set_layout({
                "cols": [0.0, 0.5, 1.0],
                "rows": [0.0, 1.0],
                "cells": [[0, 0, 1, 1], [1, 0, 2, 1]]
            })
            self.panel = win.new_file()
            win.set_view_index(self.panel, 1, 0)
            win.focus_view(activeView)

        self.panel.settings().set('line_numbers', False)
        self.panel.set_name(PANELTITLE)
        self.panel.set_scratch(True)
        self.panel.set_syntax_file("Packages/Python/Python.tmLanguage")
        # self.panel.set_read_only(True)
        self.panel.show(self.panel.size())

class CloseMayaHistoryCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        ''' Close the maya history view '''
        win = sublime.active_window()
        matchingViews = filter(lambda v: v.name() == PANELTITLE, win.views())
        self.panel = matchingViews[0] if len(matchingViews) else None
        if self.panel is not None:
            g, i = win.get_view_index(self.panel)
            win.run_command("close_by_index", { "group": g, "index": i})
            # If the window group is now empty, close it
            if len(win.views_in_group(g)) < 1:
                win.set_layout({
                    "cols": [0.0, 1.0],
                    "rows": [0.0, 1.0],
                    "cells": [[0, 0, 1, 1]]
                })

class ClearMayaHistoryCommand(sublime_plugin.TextCommand):
    ''' Clear the maya history panel '''
    def run(self, edit):
        ''' Main run method '''
        matchingViews = filter(lambda v: v.name() == PANELTITLE, sublime.active_window().views())
        self.panel = matchingViews[0] if len(matchingViews) else None

        # Clear the panel
        if self.panel:
            panel_edit = self.panel.begin_edit()
            self.panel.erase(panel_edit, sublime.Region(0, self.panel.size()))
            self.panel.end_edit(panel_edit)
            self.panel.show(self.panel.size())

class StopWatchingMayaHistoryCommand(sublime_plugin.TextCommand):
    ''' Stop any threads watching maya history '''
    def run(self, edit):
        ''' Main run method '''
        global CONTINUE
        CONTINUE = False

class SendToMayaCommand(sublime_plugin.TextCommand):
    ''' Send a python command to maya '''

    PY_CMD_TEMPLATE = '''import __main__
import traceback
try:
    exec(\'\'\'%s\'\'\', __main__.__dict__, __main__.__dict__)
except Exception,e:
    traceback.print_exc()
    print e'''

    PY_CMD_SINGLE_TEMPLATE = '''import pprint;
pp = pprint.PrettyPrinter(indent=2);
pp.pprint(%s)'''

    SINGLELINE_REGEX = re.compile(r"[ =]")

    def run(self, edit, lang="python"):
        # self.view.window().run_command("watch_maya_history")

        host = _settings['host'] 
        port = _settings['py_port']

        snips = []
        regions = []
        for sel in self.view.sel():
            if not sel.empty():
                regions.append(sel)
        if not len(regions):
            regions.append(sublime.Region(0, self.view.size()))
        for region in regions:
            lines = []
            whitespace = 100
            for line in re.split(r'[\r\n]+', self.view.substr(region)):
                if not re.match(r'^//|#', line):
                    line = line.replace(r"'''", r"\'\'\'")
                    lineWhitespace = len(line) - len(line.lstrip())
                    if lineWhitespace < whitespace:
                        whitespace = lineWhitespace 
                    lines.append(line)
            if whitespace > 0:
                lines = [l[whitespace:] for l in lines]
            snips.extend(lines)

        mCmd = str('\n'.join(snips))
        if not mCmd:
            return
        
        print 'Sending:\n%s\n' % mCmd[:200]

        if len(snips) == 1:
            matches = self.SINGLELINE_REGEX.findall(snips[0])
            if not matches:
                mCmd = self.PY_CMD_SINGLE_TEMPLATE % mCmd
        mCmd = self.PY_CMD_TEMPLATE % mCmd

        c = None

        try:
            c = Telnet(host, int(port), timeout=5)
            c.write(mCmd)
        except Exception, e:
            err = str(e)
            MSGQUEUE.put("ERROR: Unable to connect to maya. Make sure the Command Socket is open.\n")
            LOG.error(
                "Failed to communicate with Maya (%(host)s:%(port)s)):\n%(err)s" % locals()
            )
            raise
        else:
            time.sleep(.1)
        finally:
            if c is not None:
                c.close()

def settings_obj():
    return sublime.load_settings("MayaSublime.sublime-settings")

def sync_settings():
    global _settings
    so = settings_obj()
    _settings['host']       = so.get('maya_hostname')
    _settings['py_port']    = so.get('python_command_port')

settings_obj().clear_on_change("MayaSublime.settings")
settings_obj().add_on_change("MayaSublime.settings", sync_settings)
sync_settings()