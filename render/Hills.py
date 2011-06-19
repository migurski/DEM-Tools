from math import pi, sin, cos, log
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
    specular = numpy.power(specular, 10)

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
