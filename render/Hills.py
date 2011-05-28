from math import pi, sin, cos
from urlparse import urljoin, urlparse
from os.path import join

from TileStache.Caches import Disk
from TileStache.Config import Configuration
from TileStache.Core import Layer, Metatile
from TileStache.Geography import SphericalMercator

from osgeo import gdal
from PIL import Image

import numpy

def arr2img(ar):
    """ Convert Numeric.array to PIL.Image.
    """
    return Image.fromstring('L', (ar.shape[1], ar.shape[0]), ar.astype('b').tostring())

def bytes2slope(bytes):
    """ Convert slope from 8-bit to floating point.
    
        Slope returned in radians, from 0 for sheer face to pi/2 for flat ground.
    """
    return pi/2 - numpy.arcsin(bytes.astype(numpy.float32) / 0xFF)

def bytes2aspect(bytes):
    """ Convert aspect from 8-bit to floating point.
    
        Aspect returned in radians, counterclockwise from -pi at north around to pi.
    """
    return (2 * bytes.astype(numpy.float32)/0xFF - 1) * pi

class SeededLayer (Layer):
    """
    """
    def __init__(self, source):
        """
        """
        cache = Disk(source, dirs='safe')
        config = Configuration(cache, '.')
        Layer.__init__(self, config, SphericalMercator(), Metatile())
        
        self.provider = None

    def name(self):
        return '.'
    
    def dataset(self, coord):
        return self.config.cache.read(self, coord, 'TIFF')

class Provider:
    
    def __init__(self, layer, datadir):
        self.layer = layer
        
        #
        # Use Caches.Disk to build file paths
        #
        datadir = urljoin(layer.config.dirpath, datadir)
        scheme, host, path, p, q, f = urlparse(datadir)
        assert scheme in ('file', '')
        self.datadir = path
    
    def renderTile(self, width, height, srs, coord):
        """
        """
        z, x, y = '%d' % coord.zoom, '%06d' % coord.column, '%06d' % coord.row
        path = '/'.join((z, x[:3], x[3:], y[:3], y[3:])) + '.tiff'
        path = join(self.datadir, path)
        
        ds = gdal.Open(str(path))
        
        slope = bytes2slope(ds.GetRasterBand(1).ReadAsArray())
        aspect = bytes2aspect(ds.GetRasterBand(2).ReadAsArray())
        
        azimuth, altitude, deg2rad = 315.0, 85.0, pi/180
        specular = sin(altitude * deg2rad) * numpy.sin(slope) \
                 + cos(altitude * deg2rad) * numpy.cos(slope) \
                 * numpy.cos((azimuth - 90.0) * deg2rad - aspect)
        
        specular = numpy.power(specular, 20)
        
        azimuth, altitude, deg2rad = 315.0, 40.0, pi/180
        diffuse = sin(altitude * deg2rad) * numpy.sin(slope) \
                + cos(altitude * deg2rad) * numpy.cos(slope) \
                * numpy.cos((azimuth - 90.0) * deg2rad - aspect)
        
        shaded = .35 * diffuse + (.65 * specular)
        
        return arr2img(0xFF * shaded.clip(0, 1))
        
        raise Exception((self.datadir, ds, shaded))
