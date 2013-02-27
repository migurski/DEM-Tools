from math import pi, log
from tempfile import mkstemp
from os import close, write, remove
from urlparse import urljoin, urlparse
from os.path import join, exists
from urllib import urlopen

from TileStache.Geography import SphericalMercator

from PIL.Image import BILINEAR as resample
import numpy

from . import arr2img, read_slope_aspect, shade_hills

def get_slope_aspect(source_dir, coord):
    """ Retrieve slope and aspect for a coordinate tile in a source directory.
    
        Source directory can be a local path, absolute path or URL.
    """
    #
    # Find a file to work with
    #
    z, x, y = '%d' % coord.zoom, '%06d' % coord.column, '%06d' % coord.row
    tile_path = '/'.join((z, x[:3], x[3:], y[:3], y[3:])) + '.tiff'
    
    scheme, host, dir_path, p, q, f = urlparse(source_dir)
    
    if scheme in ('file', ''):
        # Local files are read directly
        return read_slope_aspect(join(dir_path, tile_path))
    
    if scheme != 'http':
        raise IOError('Unknown scheme "%s"' % scheme)

    try:
        # Remote tiles have to be downloaded first for GDAL.
        tile_href = urljoin(source_dir.rstrip('/')+'/', tile_path)
        handle, tile_path = mkstemp(prefix='hillup-tile-', suffix='.tiff')
        
        write(handle, urlopen(tile_href).read())
        close(handle)
        
        return read_slope_aspect(join(dir_path, tile_path))
    
    finally:
        # No matter what happens, keep the local filesystem clean.
        remove(tile_path)

def render_tile(source_dir, coord, min_zoom):
    """ Render a single tile.

        Looks for two-band slope+aspect TIFF files in the provided source
        directory and applies a basic hillshading algorithm before returning
        a simple grayscale PIL image with flat ground shaded to 50% gray.
        
        Check lower zoom levels for DEM files if the requested zoom
        is not immediately available, but stop checking at min_zoom.
        
        Source directory can be a local path, absolute path or URL.
    """
    original = coord.copy()
    
    if original.zoom < min_zoom:
        raise Exception('Unable to find a suitable DEM tile for tile %d/%d/%d at zoom %d or above.' % (original.zoom, original.column, original.row, min_zoom))
    
    while coord.zoom >= min_zoom:
        #
        # Basic hill shading
        #
        try:
            slope, aspect = get_slope_aspect(source_dir, coord)
        except IOError:
            # File not found, zoom out and try again.
            coord = coord.zoomBy(-1).container()
            continue
        else:
            shaded = shade_hills(slope, aspect)

        #
        # Flat ground to 50% gray exactly by way of an exponent.
        #
        flat = numpy.array([pi/2], dtype=float)
        flat = shade_hills(flat, flat)[0]
        exp = log(0.5) / log(flat)
        
        shaded = numpy.power(shaded, exp)

        #
        # Extract the desired tile out of the shaded image, if necessary.
        #
        h, w = shaded.shape
        
        if coord.zoom < original.zoom:
            ul = original.zoomTo(coord.zoom).left(coord.column).up(coord.row)
            lr = original.down().right().zoomTo(coord.zoom).left(coord.column).up(coord.row)
            
            left, top, right, bottom = map(int, (ul.column * w, ul.row * h, lr.column * w, lr.row * h))
            
            shaded = shaded[top:bottom, left:right]
        
        return arr2img(0xFF * shaded.clip(0, 1)).resize((w, h), resample)
    
    raise Exception('Unable to find a suitable DEM tile for tile %d/%d/%d at zoom %d or above.' % (original.zoom, original.column, original.row, min_zoom))

class Provider:
    """ TileStache provider for rendering hillshaded tiles.
        
        Uses render_tile() to do the actual rendering legwork.

        See http://tilestache.org/doc/#custom-providers for information
        on how the Provider object interacts with TileStache.

        Source directory can be a local path, absolute path or URL, and
        will be interpreted relative to the layer's configuration path.
    """
    def __init__(self, layer, source_dir):
        self.layer = layer
        
        source_dir = urljoin(layer.config.dirpath, source_dir)
        scheme, host, path, p, q, f = urlparse(source_dir)
        assert scheme in ('http', 'file', '')

        self.source_dir = path if (scheme == '') else '%(scheme)s://%(host)s%(path)s' % locals()
    
    def renderTile(self, width, height, srs, coord):
        """
        """
        if srs != SphericalMercator().srs:
            raise Exception('Tile projection must be spherical mercator, not "%(srs)s"' % locals())
        
        rendered = render_tile(self.source_dir, coord, 0)

        if rendered.size != (width, height):
            rendered = rendered.resize((width, height), resample)

        return rendered
