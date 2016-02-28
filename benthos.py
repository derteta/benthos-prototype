#!/usr/bin/env python
from __future__ import with_statement

from os import listdir, getcwd, system
from os.path import join, isdir, abspath, expanduser, split, exists
from functools import partial
import sys
from subprocess import call, Popen, PIPE
from fnmatch import fnmatch

from Tkinter import Tk, Listbox, Entry, END, mainloop, Grid, N, S, E, W, StringVar

LEAVE_ITEM = '..'
BOOKMARK_URL = 'bookmarks://'
BOOKMARK_FILE = expanduser('~/.benthos_bookmarks')
REVEAL_IN_FINDER = """
    tell application "Finder"
        reveal POSIX file "%s"
        activate
    end tell
"""

root = Tk()
root.geometry("800x500")

Grid.columnconfigure(root, 0, weight=1)
Grid.columnconfigure(root, 1, weight=1)
Grid.rowconfigure(root, 0, weight=1)

left_panel = Listbox(root, exportselection=0)
right_panel = Listbox(root, exportselection=0)
command_string = StringVar(root)
command_line = Entry(root, textvariable=command_string)

left_panel.grid(row=0, column=0, sticky=N+S+E+W)
right_panel.grid(row=0, column=1, sticky=N+S+E+W)
command_line.grid(row=1, column=0, columnspan=2, sticky=N+S+E+W)


def path_components(path):
    components = []
    while True:
        path, folder = split(path)

        if folder != "":
            components.append(folder)
        else:
            if path != "":
                components.append(path)
            break

    return list(reversed(components))


class FolderItem(object):

    def __init__(self, name=None, path=None):
        assert not None in (name, path)
        self._name = name
        self._path = path
        self._is_folder = isdir(path)

    @property
    def name(self):
        return self._name
    @property
    def path(self):
        return self._path
    @property
    def is_folder(self):
        return self._is_folder

    def __eq__(self, other):
        return other is not None and self.path == other.path


def encoded_string(string):
    return unicode(string, encoding='utf-8') if isinstance(string, str) else string

class Bookmarks(object):

    def __init__(self):
        self._items = []
        if exists(BOOKMARK_FILE):
            with open(expanduser(BOOKMARK_FILE), 'r') as f:
                for line in f.read().splitlines():
                    name_and_path = line.split(';')
                    full_path = abspath(encoded_string(name_and_path[-1]))
                    if exists(full_path):
                        name = name_and_path[0] \
                                if len(name_and_path) > 1 \
                                else path_components(full_path)[-1]
                        self._items.append(FolderItem(name=name, path=full_path))

    @property
    def items(self):
        return self._items


def is_bookmarks(path):
    return path == BOOKMARK_URL


def list_dir(path, bookmarks=Bookmarks()):
    if is_bookmarks(path):
        return bookmarks.items
    else:
        items = []
        for item in listdir(path):
            try:
                item = encoded_string(item)
            except UnicodeDecodeError:
                print item
                raise
            items.append(FolderItem(name=item, path=join(path, item)))
        return items


def prepare_path(path):
    return u"'" + path + u"'"

def set_title(title):
    global root
    root.title('benthos - %s' % title)


class FocusHandler(object):

    def __init__(self, panel1, panel2, command_line):
        self._panels = [panel1, panel2]
        self.command_line = command_line
        for panel in self._panels:
            panel.listbox.bind('<FocusIn>', partial(self.on_panel_focus, panel))

    def on_panel_focus(self, panel, _event):
        panel.show_path()
        self.command_line.source_panel = panel
        self.command_line.target_panel = self._panels[(self._panels.index(panel) + 1) % len(self._panels)]


class FolderData(object):

    def __init__(self, path):
        self.path = path
        self._show_dotitems = True
        self.item_changed_callback = lambda: None
        self.set_filter(None)

    @property
    def sorted_items(self):
        all_items = list_dir(self.path)
        folders = []
        files = []
        for item in all_items:
            (folders if item.is_folder else files).append(item)
        return folders + files

    @property
    def show_dotitems(self):
        return self._show_dotitems
    @show_dotitems.setter
    def show_dotitems(self, show):
        self._show_dotitems = show
        self.update()

    def path_at_index(self, index):
        return self.items[index].path

    def update(self):
        items = filter(lambda i: fnmatch(i.name, self.item_filter), self.sorted_items)
        self.items = [
            FolderItem(
                name=LEAVE_ITEM,
                path=abspath(join(self.path, LEAVE_ITEM))
            )
        ] + filter(
            lambda i: fnmatch(i.name, ('*' if self.show_dotitems else '[!.]*')),
            items
        )
        self.item_changed_callback()

    def set_filter(self, item_filter):
        self.item_filter = item_filter or '*'
        self.update()

    def go_to(self, new_path):
        if not is_bookmarks(new_path):
            if new_path.startswith('./') or not new_path.startswith('/'):
                new_path = join(self.path, new_path)
            new_path = abspath(expanduser(new_path))
        if is_bookmarks(new_path) or isdir(new_path) and self.path != new_path:
            self.set_filter(None)
            self.path = new_path
            self.update()

    def open_file(self, full_path):
        call(['open', full_path])

    def trigger_item(self, index):
        item = self.items[index]
        if item.is_folder:
            self.go_to(item.path)
        else:
            self.open_file(item.path)

    def leave(self):
        self.go_to(abspath(join(self.path, LEAVE_ITEM)))

    def enter(self, index):
        new_path = self.path_at_index(index)
        if isdir(new_path):
            self.go_to(new_path)

    def preview(self, index):
        if self.items[index].name != LEAVE_ITEM:
            item_path = self.path_at_index(index)
            p = Popen(['osascript', '-', '2', '2'], stdin=PIPE)
            p.communicate(REVEAL_IN_FINDER % item_path)


class ListBoxHandler(object):

    SEARCH_CHARS = 'abcdefghijklmnopqrstuvwxyz0123456789'

    def __init__(self, listbox, folder, handle_key_callback):
        self.search_string = ''
        self.listbox = listbox
        self.folder = folder

        listbox.bind('<Return>', self.on_enter)
        listbox.bind('<Key>', self.on_key)
        listbox.bind('<<ListboxSelect>>', self.on_selection)
        self.on_selection()

        self.handle_key = handle_key_callback
        folder.item_changed_callback = self.update

        self.update()

    def reset_search(self):
        self.search_string = ''
        self.reset_filter()

    def select_index(self, index):
        if 0 <= index < self.listbox.size():
            self.listbox.selection_clear(0, END)
            self.listbox.selection_set(index)
            self.listbox.activate(index)
            self.listbox.see(index)
            self.on_selection()

    def fill_listbox(self):
        self.listbox.delete(0, END)
        for index, item in enumerate(self.folder.items):
            item_format = u'/%s' if item.is_folder else u'  %s'
            self.listbox.insert(END, item_format % item.name)
            self.listbox.itemconfig(END, bg='white smoke' if index % 2 else 'white')

    def restore_selection(self):
        print self._selected_path
        old_selection = self._selected_path
        items = self.folder.items
        item_to_select = (
            filter(
                lambda i: i.name != LEAVE_ITEM and old_selection.startswith(i.path),
                items
            ) or [None]
        )[0]
        self.select_index(
            items.index(item_to_select)
            if item_to_select in items
            else 0
        )

    def update(self):
        self.search_string = ''
        self.fill_listbox()
        self.restore_selection()
        self.show_path()

    def show_path(self):
        set_title(self.path)

    def toggle_dotitems(self):
        self.folder.show_dotitems = not self.folder.show_dotitems

    def reset_filter(self):
        self.folder.set_filter(None)

    @property
    def path(self):
        return self.folder.path

    @property
    def selected_index(self):
        indexes = self.listbox.curselection()
        return int(indexes[0]) if indexes else None

    @property
    def selected_item(self):
        return None \
                if self.selected_index is None \
                else self.folder.items[self.selected_index]

    def on_enter(self, *_):
        self.folder.trigger_item(self.selected_index)

    def on_selection(self, *_):
        item = self.selected_item
        self._selected_path = item.path if item != None else ''

    def extend_search_string(self, character):
        new_search_string = self.search_string + character.upper()
        items = [item.name.upper() for item in self.folder.items]
        matches = filter(lambda i: i.startswith(new_search_string), items)
        if matches:
            self.search_string = new_search_string
            self.select_index(items.index(matches[0]))

    def on_key(self, event):
        print 'PANEL', event.char, event.keycode, event.keysym, event.state
        if event.state == 0 and event.char in self.SEARCH_CHARS:
            self.extend_search_string(event.char)
        else:
            if event.state == 0: # no modifiers
                key_map = {
                    'Escape': self.reset_search,
                }
            elif event.state == 4: # Ctrl
                key_map = {
                    'h': self.folder.leave,
                    'j': lambda: self.select_index(self.selected_index + 1),
                    'k': lambda: self.select_index(self.selected_index - 1),
                    'l': lambda: self.folder.enter(self.selected_index),
                    'p': lambda: self.folder.preview(self.selected_index),
                    'b': lambda: self.folder.go_to(BOOKMARK_URL),
                    'period': self.toggle_dotitems,
                }
            else:
                key_map = {
                    'Left': self.folder.leave,
                    'Right': lambda: self.folder.enter(self.selected_index),
                }
            key_map.get(event.keysym, partial(self.handle_key, event))()



class CommandHandler(object):

    def __init__(self, command_line, command_string):
        self.command_line = command_line
        self.command_line.bind('<Return>', self.on_command)
        self.command_line.bind('<Escape>', self.on_clear)
        self.command_line.bind('<FocusIn>', self.on_focus)
        self.command_line.bind('<Key>', self.on_key)
        self.command_string = command_string
        self.command_string.trace('w', self.on_string)
        self.source_panel = None
        self.target_panel = None
        self._wants_focus = False

    def on_command(self, _event):
        command = encoded_string(self.command_line.get())
        if command is not '' and not command.startswith('/'):
            if command.startswith('cd '):
                self.source_panel.folder.go_to(command[3:])
            elif command.startswith('show '):
                self.source_panel.folder.set_filter(command[5:])
            else:
                cd_cmd = 'cd %s' % self.source_panel.path # for relative paths
                system('%s && %s' % (cd_cmd, command))
                self.source_panel.folder.update()
                self.target_panel.folder.update()
        self.source_panel.listbox.focus_set()

    def on_string(self, _name, string, _mode):
        string = self.command_string.get()
        if string.startswith('/'):
            self.source_panel.folder.set_filter(u"*%s*" % string[1:])

    def do_focus(self, string=''):
        self._wants_focus = True
        self.fill_command_line(string)
        self.command_line.focus_set()

    def do_mkdir(self):
        self.do_focus()
        self.fill_command_line('mkdir ')

    def do_copy(self):
        target_folder = self.target_panel.path
        source_folder = self.source_panel.path
        source_item = self.source_panel.selected_item
        if target_folder != source_folder \
            and not target_folder.startswith(source_item.path)\
            and source_item is not None \
            and source_item.name != LEAVE_ITEM:
            self.do_focus()
            flags = '-r' if source_item.is_folder else ''
            self.fill_command_line(
                'cp %s %s %s' % (
                    flags,
                    prepare_path(source_item.path),
                    prepare_path(target_folder),
                )
            )

    def do_move(self):
        target_folder = self.target_panel.path
        source_folder = self.source_panel.path
        source_item = self.source_panel.selected_item
        if target_folder != source_folder \
            and not target_folder.startswith(source_item.path)\
            and source_item is not None \
            and source_item.name != LEAVE_ITEM:
            self.do_focus()
            self.fill_command_line(
                u"mv %s %s" % (
                    prepare_path(source_item.path),
                    prepare_path(target_folder)
                )
            )

    def do_delete(self):
        source_item = self.source_panel.selected_item
        if source_item is not None and source_item.name != LEAVE_ITEM:
            self.do_focus()
            flags = '-r' if source_item.is_folder else ''
            self.fill_command_line(
                'rm %s %s' % (flags, prepare_path(source_item.path))
            )

    def do_equal_paths(self):
        item = self.source_panel.selected_item
        path = item.path if item.is_folder else self.source_panel.path
        self.target_panel.folder.go_to(path)

    def do_reload(self):
        self.source_panel.update()
        self.target_panel.update()

    def on_key(self, event):
        if event.state in (0, 1):
            pass
        else:
            self.source_panel.on_key(event)

    def on_foreign_key(self, event):
        if event.state == 4: # Ctrl
            key_map = {
                'e': self.do_equal_paths,
                'r': self.do_reload,
            }
        else:
            key_map = {
                'colon': self.do_focus,
                'slash': lambda: self.do_focus('/'),
                'F5': self.do_copy,
                'F6': self.do_move,
                'F7': self.do_mkdir,
                'F8': self.do_delete,
            }
        key_map.get(event.keysym, lambda: None)()

    def on_clear(self, _event):
        self.command_line.delete(0, END)
        self.source_panel.reset_filter()
        self.source_panel.listbox.focus_set()

    def on_focus(self, _event):
        if not self._wants_focus:
            self.target_panel.listbox.focus_set()
        self._wants_focus = False

    def fill_command_line(self, command):
        self.command_line.delete(0, END)
        self.command_line.insert(0, command)


path = getcwd() if len(sys.argv) == 1 else abspath(sys.argv[1])

command_handler = CommandHandler(command_line, command_string)
left_handler = ListBoxHandler(left_panel, FolderData(path), command_handler.on_foreign_key)
right_handler = ListBoxHandler(right_panel, FolderData(path), command_handler.on_foreign_key)

focus_handler = FocusHandler(left_handler, right_handler, command_handler)

left_panel.focus_set()
mainloop()
