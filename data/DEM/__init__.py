""" Starting point for DEM retrieval utilities.
"""
from math import pi, sin, cos
from os import unlink, close
from itertools import product
from tempfile import mkstemp

import NED10m, SRTM1, SRTM3

from ModestMaps.Core import Coordinate
from TileStache.Geography import SphericalMercator

from osgeo import gdal, osr
from PIL import Image

import numpy

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

class Provider:
    """ TileStache provider for generating tiles of DEM slope and aspect data.

        See http://tilestache.org/doc/#custom-providers for information
        on how the Provider object interacts with TileStache.
    """
    def __init__(self, layer):
        pass
    
    def getTypeByExtension(self, ext):
        if ext.lower() != 'tiff':
            raise Exception()
        
        return 'image/tiff', 'TIFF'
    
    def renderArea(self, width, height, srs, xmin, ymin, xmax, ymax, zoom):
        """ Return an instance of SlopeAndAspect for requested area.
        """
        assert srs == webmerc_proj.srs # <-- good enough for now
        
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
        
        elevation = numpy.zeros((width+2, height+2), numpy.float32)
        
        for (module, proportion) in choose_providers(zoom):
        
            cs2cs = osr.CoordinateTransformation(webmerc_sref, module.sref)
            
            minlon, minlat, z = cs2cs.TransformPoint(xmin, ymin)
            maxlon, maxlat, z = cs2cs.TransformPoint(xmax, ymax)
            
            ds_provider = memory_dataset(width+2, height+2, area_wkt, buffered_xform)
            
            for ds_in in module.datasources(minlon, minlat, maxlon, maxlat):
                gdal.ReprojectImage(ds_in, ds_provider, ds_in.GetProjection(), ds_provider.GetProjection(), gdal.GRA_Cubic)
                ds_in.FlushCache()
            
            elevation += ds_provider.ReadAsArray() * proportion
            ds_provider.FlushCache()
        
        #
        # Calculate and save slope and aspect.
        #
        
        slope, aspect = calculate_slope_aspect(elevation, xres, yres)
        
        tile_xform = xmin, xres, 0, ymax, 0, yres
        
        return SlopeAndAspect(slope, aspect, area_wkt, tile_xform)

class SlopeAndAspect:
    """ TileStache response object with PIL-like save() and crop() methods.
    
        This object knows only how to save two-band 8-bit GeoTIFFs.
        
        See http://tilestache.org/doc/#custom-providers for information
        on how the SlopeAndAspect object interacts with TileStache.
    """
    def __init__(self, slope, aspect, wkt, xform):
        """ Instantiate with array of slope and aspect, and minimal geographic information.
        """
        self.slope = slope
        self.aspect = aspect
        
        self.w, self.h = self.slope.shape

        self.wkt = wkt
        self.xform = xform
    
    def save(self, output, format):
        """ Save a two-band GeoTIFF to output file-like object.
        """
        assert format == 'TIFF'
        
        try:
            handle, filename = mkstemp(prefix='slope-aspect-', suffix='.tif')
            close(handle)
            
            driver = gdal.GetDriverByName('GTiff')
            gtiff_options = ['COMPRESS=JPEG', 'JPEG_QUALITY=95', 'INTERLEAVE=BAND']
            ds_both = driver.Create(filename, self.w, self.h, 2, gdal.GDT_Byte, gtiff_options)
            
            ds_both.SetGeoTransform(self.xform)
            ds_both.SetProjection(self.wkt)
            
            band_slope = ds_both.GetRasterBand(1)
            band_slope.SetRasterColorInterpretation(gdal.GCI_Undefined)
            band_slope.WriteRaster(0, 0, self.w, self.h, slope2bytes(self.slope).tostring())
            
            band_aspect = ds_both.GetRasterBand(2)
            band_aspect.SetRasterColorInterpretation(gdal.GCI_Undefined)
            band_aspect.WriteRaster(0, 0, self.w, self.h, aspect2bytes(self.aspect).tostring())
            
            ds_both.FlushCache()
            output.write(open(filename, 'r').read())
        
        finally:
            unlink(filename)
    
    def crop(self, box):
        """ Returns a rectangular region from the current image.
        
            Box is a 4-tuple with left, upper, right, and lower pixels.
            Not yet implemented!
        """
        raise NotImplementedError()

def memory_dataset(width, height, wkt, xform):
    """ Return a new in-memory dataset matching the requested geometry.
    
        Use global vsimem_counter to prevent them from stepping on one another.
    """
    global vsimem_counter

    driver = gdal.GetDriverByName('GTiff')
    dataset = driver.Create('/vsimem/%d.tif' % vsimem_counter, width, height, 1, gdal.GDT_Float32)
    
    dataset.SetGeoTransform(xform)
    dataset.SetProjection(wkt)
    
    vsimem_counter += 1
    return dataset

def choose_providers(zoom):
    """ Return a list of data sources and proportions for given zoom level.
    
        Each data source is a module such as SRTM1 or SRTM3, and the proportions
        must all add up to one. Return list has either one or two items.
    """
    if zoom < SRTM3.ideal_zoom:
        return [(SRTM3, 1)]

    elif SRTM3.ideal_zoom <= zoom and zoom < SRTM1.ideal_zoom:
        bottom, top = SRTM3, SRTM1

    elif SRTM1.ideal_zoom <= zoom and zoom < NED10m.ideal_zoom:
        bottom, top = SRTM1, NED10m

    elif NED10m.ideal_zoom <= zoom:
        return [(NED10m, 1)]

    difference = top.ideal_zoom - bottom.ideal_zoom
    proportion = 1. - (zoom - bottom.ideal_zoom) / difference

    return [(bottom, proportion), (top, 1 - proportion)]

def slope2bytes(slope):
    """ Convert slope from floating point to 8-bit.
    
        Slope given in radians, from 0 for sheer face to pi/2 for flat ground.
    """
    return (0xFF * numpy.sin(slope + pi/2)).astype(numpy.uint8)

def aspect2bytes(aspect):
    """ Convert aspect from floating point to 8-bit.
    
        Aspect given in radians, counterclockwise from -pi at north around to pi.
    """
    return (0xFF * (aspect/pi + 1)/2).astype(numpy.uint8)

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
