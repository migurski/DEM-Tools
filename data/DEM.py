""" Starting point for DEM retrieval utilities.
"""
from sys import stderr
from math import floor, pi, sin, cos
from os import unlink, close, write, mkdir, chmod
from os.path import basename, exists, isdir, join
from httplib import HTTPConnection
from itertools import product
from urlparse import urlparse
from tempfile import mkstemp
from zipfile import ZipFile
from hashlib import md5

from ModestMaps.Core import Coordinate
from TileStache.Geography import SphericalMercator

from osgeo import gdal, osr
from PIL import Image

import numpy

source_dir = 'source'
pixel_buffer = 1

#
# Set up some useful projections.
#

osr.UseExceptions() # <-- otherwise errors will be silent and useless.

srtm1_sref = osr.SpatialReference()
srtm1_sref.ImportFromProj4('+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs')

webmerc_proj = SphericalMercator()
webmerc_sref = osr.SpatialReference()
webmerc_sref.ImportFromProj4(webmerc_proj.srs)

class Provider:
    """
    """
    def __init__(self, layer):
        pass
    
    def getTypeByExtension(self, ext):
        if ext.lower() != 'tiff':
            raise Exception()
        
        return 'image/tiff', 'TIFF'
    
    def renderArea(self, width, height, srs, xmin, ymin, xmax, ymax, zoom):
        """
        """
        assert srs == webmerc_proj.srs # <-- good enough for now
        
        #
        # Prepare a dataset of the desired extent and projection.
        #
        
        driver = gdal.GetDriverByName('GTiff')
        ds_elevation = driver.Create('/vsimem/dem-tile', width+2, height+2, 1, gdal.GDT_Float32)
        
        xres = (xmax - xmin) / ds_elevation.RasterXSize
        yres = (ymin - ymax) / ds_elevation.RasterYSize

        xform = xmin, xres, 0, ymax, 0, yres
        
        ds_elevation.SetGeoTransform(xform)
        ds_elevation.SetProjection(webmerc_sref.ExportToWkt())
        
        #
        # Reproject and merge DEM datasources into the destination dataset.
        #
        
        cs2cs = osr.CoordinateTransformation(webmerc_sref, srtm1_sref)
        
        minlon, minlat, z = cs2cs.TransformPoint(xmin, ymin)
        maxlon, maxlat, z = cs2cs.TransformPoint(xmax, ymax)
        
        for ds_in in srtm1_datasources(minlon, minlat, maxlon, maxlat):
            gdal.ReprojectImage(ds_in, ds_elevation, ds_in.GetProjection(), ds_elevation.GetProjection(), gdal.GRA_Cubic)
            ds_in.FlushCache()
        
        elevation = ds_elevation.ReadAsArray()
        ds_elevation.FlushCache()
        
        #
        # Calculate and save slope and aspect.
        #
        
        slope, aspect = calculate_slope_aspect(elevation, xres, yres)
        
        # recalculate resolution because of the 3x3 window
        xres = (xmax - xmin) / width
        yres = (ymin - ymax) / height

        webmerc_wkt = webmerc_sref.ExportToWkt()
        xform = xmin, xres, 0, ymax, 0, yres
        
        return SlopeAndAspect(slope, aspect, webmerc_wkt, xform)

class SlopeAndAspect:

    def __init__(self, slope, aspect, wkt, xform):
        self.slope = slope
        self.aspect = aspect
        
        self.w, self.h = self.slope.shape

        self.wkt = wkt
        self.xform = xform
    
    def save(self, output, format):
        """
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

def srtm1_region(lat, lon):
    """ Return the SRTM1 region number of a given lat, lon.
    
        Map of regions:
        http://dds.cr.usgs.gov/srtm/version2_1/SRTM1/Region_definition.jpg
    """
    if 38 <= lat and lat < 50 and -125 <= lon and lon < -111:
        return 1
    
    if 38 <= lat and lat < 50 and -111 <= lon and lon < -97:
        return 2
    
    if 38 <= lat and lat < 50 and -97 <= lon and lon < -83:
        return 3
    
    if 28 <= lat and lat < 38 and -123 <= lon and lon < -100:
        return 4
    
    if 25 <= lat and lat < 38 and -100 <= lon and lon < -83:
        return 5
    
    if 17 <= lat and lat < 48 and -83 <= lon and lon < -64:
        return 6
    
    if -15 <= lat and lat < 60 and ((172 <= lon and lon < 180) or (-180 <= lon and lon < -129)):
        return 7
    
    raise ValueError('Unknown location: %s, %s' % (lat, lon))

def srtm1_quads(minlon, minlat, maxlon, maxlat):
    """ Generate a list of southwest (lon, lat) for 1-degree quads of SRTM1 data.
    """
    lon = floor(minlon)
    while lon <= maxlon:
    
        lat = floor(minlat)
        while lat <= maxlat:
        
            yield lon, lat
        
            lat += 1
    
        lon += 1

def srtm1_datasource(lat, lon):
    """ Return a gdal datasource for an SRTM1 lat, lon corner.
    
        If it doesn't already exist locally in source_dir, grab a new one.
    """
    #
    # Create a URL
    #
    try:
        reg = srtm1_region(lat, lon)
    except ValueError:
        # we're probably outside a known region
        return None

    fmt = 'http://dds.cr.usgs.gov/srtm/version2_1/SRTM1/Region_%02d/N%dW%d.hgt.zip'
    url = fmt % (reg, abs(lat), abs(lon))
    
    #
    # Create a local filepath
    #
    s, host, path, p, q, f = urlparse(url)
    
    dem_dir = md5(url).hexdigest()[:2]
    dem_dir = join(source_dir, dem_dir)
    
    dem_path = join(dem_dir, basename(path)[:-4])
    
    #
    # Check if the file exists locally
    #
    if exists(dem_path):
        return gdal.Open(dem_path, gdal.GA_ReadOnly)

    if not exists(dem_dir):
        mkdir(dem_dir)
        chmod(dem_dir, 0777)
    
    assert isdir(dem_dir)
    
    #
    # Grab a fresh remote copy
    #
    print >> stderr, 'Retrieving', url, 'in DEM.srtm1_datasource().'
    
    conn = HTTPConnection(host, 80)
    conn.request('GET', path)
    resp = conn.getresponse()
    
    assert resp.status == 200, (resp.status, resp.read())
    
    try:
        #
        # Get the DEM out of the zip file
        #
        handle, zip_path = mkstemp(prefix='srtm1-', suffix='.zip')
        write(handle, resp.read())
        close(handle)
        
        zipfile = ZipFile(zip_path, 'r')
        
        #
        # Write the actual DEM
        #
        dem_file = open(dem_path, 'w')
        dem_file.write(zipfile.read(zipfile.namelist()[0]))
        dem_file.close()
        
        chmod(dem_path, 0666)
    
    finally:
        unlink(zip_path)

    #
    # The file better exist locally now
    #
    return gdal.Open(dem_path, gdal.GA_ReadOnly)

def tile_bounds(coord, sref, buffer=0):
    """ Retrieve bounding box of a tile coordinate in specified projection.
    
        If provided, buffer by a given number of fractional rows/columns.
    """
    # get upper left and lower right corners with specified padding
    ul = webmerc_proj.coordinateProj(coord.left(buffer).up(buffer))
    lr = webmerc_proj.coordinateProj(coord.down(1 + buffer).right(1 + buffer))
    
    cs2cs = osr.CoordinateTransformation(webmerc_sref, sref)
    
    # "min" and "max" here assume projections with positive north and east.
    xmin, ymax, z = cs2cs.TransformPoint(ul.x, ul.y)
    xmax, ymin, z = cs2cs.TransformPoint(lr.x, lr.y)
    
    return xmin, ymin, xmax, ymax

def srtm1_datasources(minlon, minlat, maxlon, maxlat):
    """ Retrieve a list of SRTM1 datasources overlapping the tile coordinate.
    """
    quads = srtm1_quads(minlon, minlat, maxlon, maxlat)
    sources = [srtm1_datasource(lat, lon) for (lon, lat) in quads]
    return [ds for ds in sources if ds]

def slope2bytes(slope):
    """ Convert slope from floating point to 8-bit.
    
        Slope given in radians, from 0 for sheer face to pi/2 for flat ground.
    """
    return (0xFF * numpy.sin(slope + pi/2)).astype(numpy.uint8)

def aspect2bytes(aspect):
    """ Convert aspect from floating point to 8-bit.
    
        Aspect given in radians, counterclockwise from -pi at north back to pi.
    """
    return (0xFF * (aspect/pi + 1)/2).astype(numpy.uint8)

def bytes2slope(bytes):
    """ Convert slope from 8-bit to floating point.
    
        Slope returned in radians, from 0 for sheer face to pi/2 for flat ground.
    """
    return pi/2 - numpy.arcsin(bytes.astype(numpy.float32) / 0xFF)

def bytes2aspect(bytes):
    """ Convert aspect from 8-bit to floating point.
    
        Aspect returned in radians, counterclockwise from -pi at north back to pi.
    """
    return (2 * bytes.astype(numpy.float32)/0xFF - 1) * pi

def calculate_slope_aspect(elevation, xres, yres, z=1.0):
    """ Return a pair of arrays 2 pixels smaller than the input elevation array.
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

if __name__ == '__main__':

    provider = Provider(None)
    coord = Coordinate(1582, 659, 12)
    
    xmin, ymin, xmax, ymax = tile_bounds(coord, webmerc_sref)
    
    image = provider.renderArea(256, 256, webmerc_proj.srs, xmin, ymin, xmax, ymax, coord.zoom)
    image.save(open('both.tif', 'w'), 'TIFF')
    
    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    
    print 'calculating shade...'
    
    azimuth, altitude = 315.0, 45.0
    
    ds_both = gdal.Open('both.tif')

    band_slope = ds_both.GetRasterBand(1)
    slope = bytes2slope(band_slope.ReadAsArray())
    
    band_aspect = ds_both.GetRasterBand(2)
    aspect = bytes2aspect(band_aspect.ReadAsArray())
    
    deg2rad = pi / 180.0
    
    shaded = sin(altitude * deg2rad) * numpy.sin(slope) \
           + cos(altitude * deg2rad) * numpy.cos(slope) \
           * numpy.cos((azimuth - 90.0) * deg2rad - aspect);
    
    shaded_data = (0xFF * shaded).astype(numpy.uint8)

    driver = gdal.GetDriverByName('GTiff')
    ds_shaded = driver.Create('shaded-j95.tif', 256, 256, 1, gdal.GDT_Byte)
    ds_shaded.WriteRaster(0, 0, shaded.shape[0], shaded.shape[1], shaded_data.tostring(), buf_type=gdal.GDT_Byte)
    ds_shaded.FlushCache()
