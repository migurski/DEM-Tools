#!/usr/bin/env python
"""
"""
from optparse import OptionParser

from TileStache import getTile
from TileStache.Caches import Disk
from TileStache.Config import Configuration
from TileStache.Core import Layer, Metatile
from TileStache.Geography import SphericalMercator

from ModestMaps.Core import Coordinate
from ModestMaps.Geo import Location

from DEM import Provider

class SeedingLayer (Layer):
    """
    """
    def __init__(self, directory):
        """
        """
        cache = Disk(directory, dirs='safe')
        config = Configuration(cache, '.')
        Layer.__init__(self, config, SphericalMercator(), Metatile())
        
        self.provider = Provider(self)

    def name(self):
        return '.'

parser = OptionParser(usage="""%prog [options] [zoom...]

Bounding box is given as a pair of lat/lon coordinates, e.g. "37.788 -122.349
37.833 -122.246". Output is a list of tile paths as they are created.

See `%prog --help` for info.""")

defaults = dict(verbose=True, directory='out', bbox=(37.777, -122.352, 37.839, -122.086))

parser.set_defaults(**defaults)

parser.add_option('-b', '--bbox', dest='bbox',
                  help='Bounding box in floating point geographic coordinates: south west north east.',
                  type='float', nargs=4)

parser.add_option('-f', '--progress-file', dest='progressfile',
                  help="Optional JSON progress file that gets written on each iteration, so you don't have to pay close attention.")

parser.add_option('-q', action='store_false', dest='verbose',
                  help='Suppress chatty output, --progress-file works well with this.')

parser.add_option('-d', '--output-directory', dest='directory',
                  help='Optional output directory for tiles, for the TileStache equivalent of this configured cache: {"name": "Disk", "path": <output directory>, "dirs": "safe", "gzip": []}. More information in http://tilestache.org/doc/#caches.')

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

    options, zooms = parser.parse_args()

    verbose = options.verbose
    progressfile = options.progressfile

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
    
    layer = SeedingLayer(options.directory)

    for (offset, count, coord) in generateCoordinates(ul, lr, zooms, 0):
        
        mimetype, content = getTile(layer, coord, 'TIFF', True)

        print coord
