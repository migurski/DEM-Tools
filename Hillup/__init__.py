from math import pi, sin, cos
from os import unlink, close
from tempfile import mkstemp
from os.path import exists

from osgeo import gdal
from PIL import Image
import numpy

__all__ = 'data', 'tiles'

def read_slope_aspect(filename):
    """ Return arrays of slope and aspect data (both in radians) from a filename.
    """
    if not exists(filename):
        raise IOError('Missing file "%s"' % filename)
    
    ds = gdal.Open(str(filename))
    
    if ds is None:
        raise IOError('Unopenable file "%s"' % filename)
    
    slope = bytes2slope(ds.GetRasterBand(1).ReadAsArray())
    aspect = bytes2aspect(ds.GetRasterBand(2).ReadAsArray())
    
    return slope, aspect

def save_slope_aspect(slope, aspect, wkt, xform, fp, tmpdir):
    """ Save arrays of slope and aspect to a GeoTIFF file pointer.
    """
    w, h = slope.shape
    
    try:
        handle, filename = mkstemp(dir=tmpdir, prefix='slope-aspect-', suffix='.tif')
        close(handle)
        
        driver = gdal.GetDriverByName('GTiff')
        gtiff_options = ['COMPRESS=JPEG', 'JPEG_QUALITY=95', 'INTERLEAVE=BAND']
        ds_both = driver.Create(filename, w, h, 2, gdal.GDT_Byte, gtiff_options)
        
        ds_both.SetGeoTransform(xform)
        ds_both.SetProjection(wkt)
        
        band_slope = ds_both.GetRasterBand(1)
        band_slope.SetRasterColorInterpretation(gdal.GCI_Undefined)
        band_slope.WriteRaster(0, 0, w, h, slope2bytes(slope).tostring())
        
        band_aspect = ds_both.GetRasterBand(2)
        band_aspect.SetRasterColorInterpretation(gdal.GCI_Undefined)
        band_aspect.WriteRaster(0, 0, w, h, aspect2bytes(aspect).tostring())
        
        ds_both.FlushCache()
        ds_both = None # GDAL is lame about actually writing data until this object is out of scope
        fp.write(open(filename, 'r').read())
    
    finally:
        unlink(filename)

def shade_hills(slope, aspect):
    """ Convert slope and aspect to 0-1 grayscale with combined light sources.
    """
    diffuse = shade_hills_onelight(slope, aspect, 315.0, 30.0)
    specular = shade_hills_onelight(slope, aspect, 315.0, 85.0)
    
    # sharpen specular shading on slopes
    specular = numpy.power(specular, 4)

    # 40% diffuse and 60% specular
    shaded = .4 * diffuse + (.6 * specular)
    
    return shaded

def shade_hills_onelight(slope, aspect, azimuth, altitude):
    """ Convert slope and aspect to 0-1 grayscale with given sun position.
    """
    deg2rad = pi/180

    shaded = sin(altitude * deg2rad) * numpy.sin(slope) \
            + cos(altitude * deg2rad) * numpy.cos(slope) \
            * numpy.cos((azimuth - 90.0) * deg2rad - aspect)
    
    return shaded

def arr2img(ar):
    """ Convert Numeric.array to PIL.Image.
    """
    return Image.fromstring('L', (ar.shape[1], ar.shape[0]), ar.astype('b').tostring())

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
