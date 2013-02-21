#!/usr/bin/env python
"""
"""
from sys import path
from os.path import exists
from optparse import OptionParser

from TileStache import getTile
from TileStache.Geography import SphericalMercator

from ModestMaps.Core import Coordinate
from ModestMaps.Geo import Location

from Hillup.data import SeedingLayer

parser = OptionParser(usage="""%prog [options] [zoom...]

Bounding box is given as a pair of lat/lon coordinates, e.g. "37.788 -122.349
37.833 -122.246". Output is a list of tile paths as they are created.

See `%prog --help` for info.""")

defaults = dict(demdir='source', tiledir='out', tmpdir=None, source='worldwide', bbox=(37.777, -122.352, 37.839, -122.086), size=256)

parser.set_defaults(**defaults)

parser.add_option('-b', '--bbox', dest='bbox',
                  help='Bounding box in floating point geographic coordinates: south west north east, default (%.3f, %.3f, %.3f, %.3f).' % defaults['bbox'],
                  type='float', nargs=4)

parser.add_option('-d', '--dem-directory', dest='demdir',
                  help='Directory for raw source elevation files, default "%(demdir)s".' % defaults)

parser.add_option('-t', '--tile-directory', dest='tiledir',
                  help='Directory for generated slope/aspect tiles, default "%(tiledir)s". This directory will be used as the "source_dir" for Hillup.tiles:Provider shaded renderings.' % defaults)

parser.add_option('--tile-list', dest='tile_list',
                  help='Optional file of tile coordinates, a simple text list of Z/X/Y coordinates. Overrides --bbox.')

parser.add_option('-s', '--source', dest='source',
                  help='Data source for elevations. One of "srtm-ned" for SRTM and NED data, "ned-only" for US-only downsample NED, "vfp" for Viewfinder Panoramas and SRTM3, "worldwide" for combined datasets (currently SRTM3 + VFP), or a function path such as "Module.Submodule:Function". Default "%(source)s".' % defaults)

parser.add_option('--tmp-directory', dest='tmpdir',
                  help='Optional working directory for temporary files. Consider a ram disk for this.')

parser.add_option('--tile-size', dest='size', type='int',
                  help='Optional size for rendered tiles, default %(size)s.' % defaults)

def generateCoordinates(ul, lr, zooms, padding):
    """ Generate a stream of (offset, count, coordinate) tuples for seeding.
    """
    # start with a simple total of all the coordinates we will need.
    count = 0
    
    for zoom in zooms:
        ul_ = ul.zoomTo(zoom).container().left(padding).up(padding)
        lr_ = lr.zoomTo(zoom).container().right(padding).down(padding)
        
        rows = lr_.row + 1 - ul_.row
        cols = lr_.column + 1 - ul_.column
        
        count += int(rows * cols)

    # now generate the actual coordinates.
    # offset starts at zero
    offset = 0
    
    for zoom in zooms:
        ul_ = ul.zoomTo(zoom).container().left(padding).up(padding)
        lr_ = lr.zoomTo(zoom).container().right(padding).down(padding)

        for row in range(int(ul_.row), int(lr_.row + 1)):
            for column in range(int(ul_.column), int(lr_.column + 1)):
                coord = Coordinate(row, column, zoom)
                
                yield (offset, count, coord)
                
                offset += 1

if __name__ == '__main__':

    path.insert(0, '.')

    options, zooms = parser.parse_args()
    
    if options.tile_list and exists(options.tile_list):

        # read out zooms, columns, rows
        zxys = [line.strip().split('/') for line in open(options.tile_list)]
        coords = [Coordinate(*map(int, (y, x, z))) for (z, x, y) in zxys]
        tiles = [(i, len(coords), coord) for (i, coord) in enumerate(coords)]
    
    else:
        lat1, lon1, lat2, lon2 = options.bbox
        south, west = min(lat1, lat2), min(lon1, lon2)
        north, east = max(lat1, lat2), max(lon1, lon2)
    
        northwest = Location(north, west)
        southeast = Location(south, east)
        
        webmerc = SphericalMercator()
    
        ul = webmerc.locationCoordinate(northwest)
        lr = webmerc.locationCoordinate(southeast)
    
        for (i, zoom) in enumerate(zooms):
            if not zoom.isdigit():
                raise KnownUnknown('"%s" is not a valid numeric zoom level.' % zoom)
    
            zooms[i] = int(zoom)
        
        tiles = generateCoordinates(ul, lr, zooms, 0)
    
    layer = SeedingLayer(options.demdir, options.tiledir, options.tmpdir, options.source, options.size)

    for (offset, count, coord) in tiles:
        
        mimetype, content = getTile(layer, coord, 'TIFF', True)

        print coord
