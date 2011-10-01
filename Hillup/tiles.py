from math import pi, sin, cos, log
from urlparse import urljoin, urlparse
from os.path import join, exists

from TileStache.Caches import Disk
from TileStache.Config import Configuration
from TileStache.Core import Layer, Metatile
from TileStache.Geography import SphericalMercator

from osgeo import gdal
import numpy

from . import arr2img, bytes2slope, bytes2aspect

def hillshade_raw(slope, aspect, azimuth, altitude):
    """ Shade hills with a single light source.
    """
    deg2rad = pi/180

    shaded = sin(altitude * deg2rad) * numpy.sin(slope) \
            + cos(altitude * deg2rad) * numpy.cos(slope) \
            * numpy.cos((azimuth - 90.0) * deg2rad - aspect)
    
    return shaded

def hillshade(slope, aspect):
    """ Shade hills with combined light sources.
    """
    diffuse = hillshade_raw(slope, aspect, 315.0, 30.0)
    specular = hillshade_raw(slope, aspect, 315.0, 85.0)
    
    # darken specular shading on slopes
    specular = numpy.power(specular, 4)

    # 40% diffuse and 60% specular
    shaded = .4 * diffuse + (.6 * specular)
    
    return shaded

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
        
        #
        # Basic hill shading
        #
        if not exists(path):
            raise Exception('Missing file "%s"' % path)
        
        ds = gdal.Open(str(path))
        
        slope = bytes2slope(ds.GetRasterBand(1).ReadAsArray())
        aspect = bytes2aspect(ds.GetRasterBand(2).ReadAsArray())
        shaded = hillshade(slope, aspect)
        
        #
        # Flat ground to 50% gray exactly by way of an exponent.
        #
        flat = numpy.array([pi/2], dtype=float)
        flat = hillshade(flat, flat)[0]
        exp = log(0.5) / log(flat)
        
        shaded = numpy.power(shaded, exp)
        
        return arr2img(0xFF * shaded.clip(0, 1))
