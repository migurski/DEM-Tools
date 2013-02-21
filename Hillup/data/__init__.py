""" Starting point for DEM retrieval utilities.
"""
from math import pi, sin, cos
from os import unlink, close
from itertools import product
from tempfile import mkstemp
from sys import modules

import NED10m, NED100m, NED1km, SRTM1, SRTM3, VFP, Worldwide

from ModestMaps.Core import Coordinate
from TileStache.Geography import SphericalMercator
from TileStache.Core import Layer, Metatile
from TileStache.Config import Configuration
from TileStache.Caches import Disk

from osgeo import gdal, osr
from PIL import Image
import numpy

from .. import save_slope_aspect

# used to prevent clobbering in /vsimem/, see:
# http://osgeo-org.1803224.n2.nabble.com/gdal-dev-Outputting-to-vsimem-td6221295.html
vsimem_counter = 1

#
# Set up some useful projections.
#

osr.UseExceptions() # <-- otherwise errors will be silent and useless.

webmerc_proj = SphericalMercator()
webmerc_sref = osr.SpatialReference()
webmerc_sref.ImportFromProj4(webmerc_proj.srs)

class SeedingLayer (Layer):
    """ Tilestache-compatible seeding layer for preparing tiled data.
    
        Intended for use in hillup-seed.py script for preparing a tile directory.
    """
    def __init__(self, demdir, tiledir, tmpdir, source, size):
        """
        """
        cache = Disk(tiledir, dirs='safe')
        config = Configuration(cache, '.')
        Layer.__init__(self, config, SphericalMercator(), Metatile(), tile_height=size)
        
        self.provider = Provider(self, demdir, tmpdir, source)

    def name(self):
        return '.'

class Provider:
    """ TileStache provider for generating tiles of DEM slope and aspect data.
    
        Source parameter can be "srtm-ned" (default) or "ned-only".

        See http://tilestache.org/doc/#custom-providers for information
        on how the Provider object interacts with TileStache.
    """
    def __init__(self, layer, demdir, tmpdir=None, source='srtm-ned'):
        self.tmpdir = tmpdir
        self.demdir = demdir
        self.source = source
    
    def getTypeByExtension(self, ext):
        if ext.lower() != 'tiff':
            raise Exception()
        
        return 'image/tiff', 'TIFF'
    
    def renderArea(self, width, height, srs, xmin, ymin, xmax, ymax, zoom):
        """ Return an instance of SlopeAndAspect for requested area.
        """
        assert srs == webmerc_proj.srs # <-- good enough for now
        
        if self.source == 'srtm-ned':
            providers = choose_providers_srtm(zoom)
        
        elif self.source == 'ned-only':
            providers = choose_providers_ned(zoom)

        elif self.source == 'vfp':
            providers = [(VFP, 1)]

        elif self.source == 'worldwide':
            providers = [(Worldwide, 1)]

        else:
            providers = load_func_path(self.source)(zoom)
        
        assert sum([proportion for (mod, proportion) in providers]) == 1.0
        
        #
        # Prepare information for datasets of the desired extent and projection.
        #
        
        xres = (xmax - xmin) / width
        yres = (ymin - ymax) / height

        area_wkt = webmerc_sref.ExportToWkt()
        buffered_xform = xmin - xres, xres, 0, ymax - yres, 0, yres
        
        #
        # Reproject and merge DEM datasources into destination datasets.
        #
        
        driver = gdal.GetDriverByName('GTiff')
        
        composite_ds = make_empty_datasource(width+2, height+2, buffered_xform, area_wkt, self.tmpdir)
        proportion_complete = 0.

        for (module, proportion) in providers:
        
            cs2cs = osr.CoordinateTransformation(webmerc_sref, module.sref)
            
            # get a lat/lon bbox buffered by one pixel on all sides
            minlon, minlat, z = cs2cs.TransformPoint(xmin - xres, ymin + yres)
            maxlon, maxlat, z = cs2cs.TransformPoint(xmax + xres, ymax - yres)
            
            #
            # Keep a version of the composite without the
            # current layer applied for later alpha-blending.
            #
            do_blending = bool(proportion_complete > 0 and proportion < 1)
            
            if do_blending:
                composite_without = composite_ds.ReadAsArray()
            
            ds_args = minlon, minlat, maxlon, maxlat, self.demdir
            
            for ds_dem in module.datasources(*ds_args):
            
                # estimate the raster density across source DEM and output
                dem_samples = (maxlon - minlon) / ds_dem.GetGeoTransform()[1]
                area_pixels = (xmax - xmin) / composite_ds.GetGeoTransform()[1]
                
                if dem_samples > area_pixels:
                    # cubic looks better squeezing down
                    resample = gdal.GRA_Cubic
                else:
                    # cubic spline looks better stretching out
                    resample = gdal.GRA_CubicSpline

                gdal.ReprojectImage(ds_dem, composite_ds, ds_dem.GetProjection(), composite_ds.GetProjection(), resample)
                ds_dem = None
            
            #
            # Perform alpha-blending if needed.
            #
            if do_blending:
                proportion_with = proportion / (proportion_complete + proportion)
                proportion_without = 1 - proportion_with
                
                composite_with = composite_ds.ReadAsArray() * proportion_with
                composite_with += composite_without * proportion_without

                composite_ds.GetRasterBand(1).WriteArray(composite_with, 0, 0)
            
            proportion_complete += proportion
                
        elevation = composite_ds.ReadAsArray()

        unlink(composite_ds.GetFileList()[0])
        composite_ds = None
        
        #
        # Calculate and save slope and aspect.
        #
        
        slope, aspect = calculate_slope_aspect(elevation, xres, yres)

        tile_xform = xmin, xres, 0, ymax, 0, yres
        
        return SlopeAndAspect(self.tmpdir, slope, aspect, area_wkt, tile_xform)

class SlopeAndAspect:
    """ TileStache response object with PIL-like save() and crop() methods.
    
        This object knows only how to save two-band 8-bit GeoTIFFs.
        
        See http://tilestache.org/doc/#custom-providers for information
        on how the SlopeAndAspect object interacts with TileStache.
    """
    def __init__(self, tmpdir, slope, aspect, wkt, xform):
        """ Instantiate with array of slope and aspect, and minimal geographic information.
        """
        self.tmpdir = tmpdir
        
        self.slope = slope
        self.aspect = aspect
        
        self.w, self.h = self.slope.shape

        self.wkt = wkt
        self.xform = xform
    
    def save(self, output, format):
        """ Save a two-band GeoTIFF to output file-like object.
        """
        if format != 'TIFF':
            raise Exception('File format other than TIFF for slope and aspect: "%s"' % format)
        
        save_slope_aspect(self.slope, self.aspect, self.wkt, self.xform, output, self.tmpdir)
    
    def crop(self, box):
        """ Returns a rectangular region from the current image.
        
            Box is a 4-tuple with left, upper, right, and lower pixels.
            Not yet implemented!
        """
        raise NotImplementedError()

def choose_providers_srtm(zoom):
    """ Return a list of data sources and proportions for given zoom level.
        
        Each data source is a module such as SRTM1 or SRTM3, and the proportions
        must all add up to one. Return list has either one or two items.
    """
    if zoom <= SRTM3.ideal_zoom:
        return [(SRTM3, 1)]

    elif SRTM3.ideal_zoom < zoom and zoom < SRTM1.ideal_zoom:
        #bottom, top = SRTM3, SRTM1 # SRTM1 looks terrible
        bottom, top = SRTM3, NED10m

    elif zoom == SRTM1.ideal_zoom:
        #return [(SRTM1, 1)] # SRTM1 looks terrible
        bottom, top = SRTM3, NED10m

    elif SRTM1.ideal_zoom < zoom and zoom < NED10m.ideal_zoom:
        #bottom, top = SRTM1, NED10m # SRTM1 looks terrible
        bottom, top = SRTM3, NED10m

    elif zoom >= NED10m.ideal_zoom:
        return [(NED10m, 1)]

    difference = float(top.ideal_zoom) - float(bottom.ideal_zoom)
    proportion = 1. - (zoom - float(bottom.ideal_zoom)) / difference

    return [(bottom, proportion), (top, 1 - proportion)]

def choose_providers_ned(zoom):
    """ Return a list of data sources and proportions for given zoom level.
    
        Each data source is a module such as NED10m or NED1km, and the proportions
        must all add up to one. Return list has either one or two items.
    """
    if zoom <= NED1km.ideal_zoom:
        return [(NED1km, 1)]

    elif NED1km.ideal_zoom < zoom and zoom < NED100m.ideal_zoom:
        #bottom, top = NED1km, NED100m
        bottom, top = NED1km, NED100m

    elif zoom == NED100m.ideal_zoom:
        return [(NED100m, 1)]

    elif NED100m.ideal_zoom < zoom and zoom < NED10m.ideal_zoom:
        #bottom, top = NED100m, NED10m
        bottom, top = NED100m, NED10m

    elif zoom >= NED10m.ideal_zoom:
        return [(NED10m, 1)]

    difference = float(top.ideal_zoom) - float(bottom.ideal_zoom)
    proportion = 1. - (zoom - float(bottom.ideal_zoom)) / difference

    return [(bottom, proportion), (top, 1 - proportion)]

def make_empty_datasource(width, height, xform, wkt, tmpdir):
    '''
    '''
    driver = gdal.GetDriverByName('GTiff')
    handle, filename = mkstemp(dir=tmpdir, prefix='dem-tools-hillup-data-render-', suffix='.tif')
    close(handle)

    ds = driver.Create(filename, width, height, 1, gdal.GDT_Float32)
    ds.SetGeoTransform(xform)
    ds.SetProjection(wkt)
    
    ds.GetRasterBand(1).WriteArray(numpy.ones((width, height), numpy.float32) * -9999, 0, 0)
    ds.GetRasterBand(1).SetNoDataValue(-9999)
    
    return ds

def calculate_slope_aspect(elevation, xres, yres, z=1.0):
    """ Return a pair of arrays 2 pixels smaller than the input elevation array.
    
        Slope is returned in radians, from 0 for sheer face to pi/2 for
        flat ground. Aspect is returned in radians, counterclockwise from -pi
        at north around to pi.
        
        Logic here is borrowed from hillshade.cpp:
          http://www.perrygeo.net/wordpress/?p=7
    """
    width, height = elevation.shape[0] - 2, elevation.shape[1] - 2
    
    window = [z * elevation[row:(row + height), col:(col + width)]
              for (row, col)
              in product(range(3), range(3))]
    
    x = ((window[0] + window[3] + window[3] + window[6]) \
       - (window[2] + window[5] + window[5] + window[8])) \
      / (8.0 * xres);
    
    y = ((window[6] + window[7] + window[7] + window[8]) \
       - (window[0] + window[1] + window[1] + window[2])) \
      / (8.0 * yres);

    # in radians, from 0 to pi/2
    slope = pi/2 - numpy.arctan(numpy.sqrt(x*x + y*y))
    
    # in radians counterclockwise, from -pi at north back to pi
    aspect = numpy.arctan2(x, y)
    
    return slope, aspect

def load_func_path(funcpath):
    """ Load external function based on a path.
        
        Example funcpath: "Module.Submodule:Function".
    """
    modname, objname = funcpath.split(':', 1)

    __import__(modname)
    module = modules[modname]
    _func = eval(objname, module.__dict__)
    
    if _func is None:
        raise Exception('eval(%(objname)s) in %(modname)s came up None' % locals())

    return _func
