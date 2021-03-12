import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
from minigalaxy.paths import CSS_PATH


CSS_PROVIDER = Gtk.CssProvider()
with open(CSS_PATH) as style:
    CSS_PROVIDER.load_from_data(style.read().encode('utf-8'))
