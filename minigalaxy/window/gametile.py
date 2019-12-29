import shutil
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GdkPixbuf, GLib
import requests
import json
import os
import threading
import subprocess
from minigalaxy.paths import CACHE_DIR, THUMBNAIL_DIR, UI_DIR


@Gtk.Template.from_file(os.path.join(UI_DIR, "gametile.ui"))
class GameTile(Gtk.Box):
    __gtype_name__ = "GameTile"

    image = Gtk.Template.Child()
    button = Gtk.Template.Child()

    def __init__(self, parent, game=None, api=None, install_dir=""):
        Gtk.Frame.__init__(self)
        self.parent = parent
        self.game = game
        self.api = api
        self.progress_bar = None
        self.installed = False
        self.install_dir = install_dir
        self.busy = False

        self.image.set_tooltip_text(self.game.name)

        self.download_dir = os.path.join(CACHE_DIR, "download")
        self.download_path = os.path.join(self.download_dir, "{}.sh".format(self.game.name))
        if not os.path.exists(CACHE_DIR):
            os.makedirs(CACHE_DIR)

        self.load_state()

        image_thread = threading.Thread(target=self.__load_image)
        image_thread.start()

    def __str__(self):
        return self.game.name

    @Gtk.Template.Callback("on_button_clicked")
    def on_button_click(self, widget) -> None:
        if self.busy:
            return
        if self.installed:
            self.__start_game()
        else:
            self.busy = True
            self.__create_progress_bar()
            widget.set_sensitive(False)
            widget.set_label("downloading...")
            download_thread = threading.Thread(target=self.__download_file)
            download_thread.start()

    def __load_image(self) -> None:
        # image_url = "https:" + self.image_url + "_392.jpg" #This is the bigger image size
        image_url = "https:{}_196.jpg".format(self.game.image_url)
        filename = os.path.join(THUMBNAIL_DIR, "{}.jpg".format(self.game.id))
        if not os.path.isfile(filename):
            download = requests.get(image_url)
            with open(filename, "wb") as writer:
                writer.write(download.content)
                writer.close()
        GLib.idle_add(self.image.set_from_file, filename)

    def __download_file(self) -> None:
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)
        download_info = self.api.get_download_info(self.game)
        file_url = download_info["downlink"]
        data = requests.get(file_url, stream=True)
        handler = open(self.download_path, "wb")

        total_size = int(data.headers.get('content-length'))
        downloaded_size = 0
        chunk_count = 0
        for chunk in data.iter_content(chunk_size=4096):
            if chunk:
                chunk_count += 1
                handler.write(chunk)
                downloaded_size += len(chunk)
                # Only update the progress bar every 2 megabytes
                if chunk_count == 4000:
                    percentage = downloaded_size / total_size
                    GLib.idle_add(self.progress_bar.set_fraction, percentage)
                    chunk_count = 0
        handler.close()
        GLib.idle_add(self.progress_bar.destroy)
        GLib.idle_add(self.button.set_label, "installing..")
        self.__install_game()
        self.busy = False
        GLib.idle_add(self.load_state)
        GLib.idle_add(self.button.set_sensitive, True)
        GLib.idle_add(self.parent.filter_library)

    def __install_game(self) -> None:
        # Make a temporary directory for extracting the installer
        temp_dir = os.path.join(CACHE_DIR, "extract/{}".format(self.game.id))
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

        os.makedirs(temp_dir)

        # Extract the game files
        subprocess.call(["unzip", "-qq", self.download_path, "-d",
                         temp_dir])

        library_dir = self.api.config.get("install_dir")
        # Make sure the install directory exists
        if not os.path.exists(library_dir):
            os.makedirs(library_dir)

        # Copy the game files into the correct directory
        shutil.move(os.path.join(temp_dir, "data/noarch"), self.__get_install_dir())
        shutil.rmtree(temp_dir, ignore_errors=True)
        os.remove(self.download_path)

    def __create_progress_bar(self) -> None:
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_halign(Gtk.Align.CENTER)
        self.progress_bar.set_size_request(196, -1)
        self.progress_bar.set_hexpand(False)
        self.progress_bar.set_vexpand(False)
        self.set_center_widget(self.progress_bar)
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.show_all()

    def __get_install_dir(self):
        if not self.install_dir or not os.path.isdir(self.install_dir):
            self.install_dir = os.path.join(self.api.config.get("install_dir"), self.game.name)
        return self.install_dir

    def __get_executable_path(self):
        return os.path.join(self.__get_install_dir(), "start.sh")

    def load_state(self) -> None:
        if self.busy:
            return
        if os.path.isfile(os.path.join(self.__get_install_dir(), "gameinfo")):
            self.installed = True
            self.button.set_label("play")
        else:
            self.installed = False
            self.button.set_label("download")

    def __start_game(self) -> subprocess:
        error_message = ""
        game = None
        try:
            game = subprocess.Popen([self.__get_executable_path()], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            # Try the goggame-*.info file to figure out what the binary is
            info_file = os.path.join(self.__get_install_dir(), "game/goggame-{}.info".format(self.game.id))
            if os.path.isfile(info_file):
                with open(info_file, 'r') as file:
                    info = json.loads(file.read())
                    print(info)
                    file.close()
                if info:
                    binary_dir = os.path.join(self.__get_install_dir(), "game")
                    os.chdir(binary_dir)
                    exec_command = "./{}".format(info["playTasks"][0]["path"])
                    game = subprocess.Popen([exec_command], stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE)
            else:
                error_message = "No executable was found in {}".format(self.__get_install_dir())

        if game:
            try:
                game.wait(timeout=float(3))
            except subprocess.TimeoutExpired:
                return game
        else:
            error_message = "Couldn't start subprocess"

        # Now deal with the error we've received
        if not error_message:
            stdout, stderror = game.communicate()
            error_message = stderror.decode("utf-8")
            if not error_message:
                error_message = "No error message was returned"

        error_text = "Failed to start {}:".format(self.game.name)
        print(error_text)
        print(error_message)
        dialog = Gtk.MessageDialog(
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text=error_text
        )
        dialog.format_secondary_text(error_message)
        dialog.run()
        dialog.destroy()

    def __lt__(self, other):
        names = [str(self), str(other)]
        names.sort()
        if names[0] == str(self):
            return True
        return False
