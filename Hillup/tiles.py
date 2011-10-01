from math import pi, sin, cos, log
from urlparse import urljoin, urlparse
from os.path import join, exists

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

class Provider:
    """ TileStache provider for rendering hillshaded tiles.
        
        Looks for two-band slope+aspect TIFF files in the provided source
        directory and applies a basic hillshading algorithm before returning
        a simple grayscale PIL image with flat ground shaded to 50% gray.

        See http://tilestache.org/doc/#custom-providers for information
        on how the Provider object interacts with TileStache.
    """
    def __init__(self, layer, source_dir):
        self.layer = layer
        
        source_dir = urljoin(layer.config.dirpath, source_dir)
        scheme, host, path, p, q, f = urlparse(source_dir)
        assert scheme in ('file', '')
        self.source_dir = path
    
    def renderTile(self, width, height, srs, coord):
        """
        """
        if srs != SphericalMercator().srs:
            raise Exception('Tile projection must be spherical mercator, not "%(srs)s"' % locals())
        
        #
        # Find a file to work with
        #
        z, x, y = '%d' % coord.zoom, '%06d' % coord.column, '%06d' % coord.row
        path = '/'.join((z, x[:3], x[3:], y[:3], y[3:])) + '.tiff'
        path = join(self.source_dir, path)
        
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
