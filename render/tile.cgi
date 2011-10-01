#!/usr/bin/python
import sys
import os, TileStache
TileStache.cgiHandler(os.environ, 'tilestache.cfg', debug=True)
