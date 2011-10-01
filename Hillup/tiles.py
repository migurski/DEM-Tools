from math import pi, log
from urlparse import urljoin, urlparse
from os.path import join, exists

from TileStache.Geography import SphericalMercator

import numpy

from . import arr2img, read_slope_aspect, shade_hills

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
        slope, aspect = read_slope_aspect(path)
        shaded = shade_hills(slope, aspect)
        
        #
        # Flat ground to 50% gray exactly by way of an exponent.
        #
        flat = numpy.array([pi/2], dtype=float)
        flat = shade_hills(flat, flat)[0]
        exp = log(0.5) / log(flat)
        
        shaded = numpy.power(shaded, exp)
        
        return arr2img(0xFF * shaded.clip(0, 1))
