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

import numpy

source_dir = 'source'
pixel_buffer = 16

#
# Set up some useful projections.
#

osr.UseExceptions() # <-- otherwise errors will be silent and useless.

srtm1_sref = osr.SpatialReference()
srtm1_sref.ImportFromProj4('+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs')

webmerc_proj = SphericalMercator()
webmerc_sref = osr.SpatialReference()
webmerc_sref.ImportFromProj4(webmerc_proj.srs)

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
    
    raise ValueError('Unknown location')

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
    reg = srtm1_region(lat, lon)
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

def tile_bounds(coord, sref, pixels=0):
    """ Retrieve bounding box of a tile coordinate in specified projection.
    
        If provided, buffer by a given number of pixels (assumes 256x256 tiles).
    """
    buffer = pixels and (float(pixels) / 256) or 0
    
    # get upper left and lower right corners with specified padding
    ul = webmerc_proj.coordinateProj(coord.left(buffer).up(buffer))
    lr = webmerc_proj.coordinateProj(coord.down(1 + buffer).right(1 + buffer))
    
    cs2cs = osr.CoordinateTransformation(webmerc_sref, sref)
    
    # "min" and "max" here assume projections with positive north and east.
    xmin, ymax, z = cs2cs.TransformPoint(ul.x, ul.y)
    xmax, ymin, z = cs2cs.TransformPoint(lr.x, lr.y)
    
    return xmin, ymin, xmax, ymax

def srtm1_datasources(coord):
    """ Retrieve a list of SRTM1 datasources overlapping the tile coordinate.
    """
    xmin, ymin, xmax, ymax = tile_bounds(coord, srtm1_sref, pixel_buffer)
    
    return [srtm1_datasource(lat, lon)
            for (lon, lat)
            in srtm1_quads(xmin, ymin, xmax, ymax)]

if __name__ == '__main__':

    coord = Coordinate(1582, 659, 12)

    #print srtm1_region(37.854525, -121.999741)
    
    xmin, ymin, xmax, ymax = tile_bounds(coord, webmerc_sref, pixel_buffer)
    width, height = 256 + pixel_buffer*2, 256 + pixel_buffer*2
    
    driver = gdal.GetDriverByName('GTiff')
    ds_elevation = driver.Create('elevation.tif', width, height, 1, gdal.GDT_Float32)
    
    xres = (xmax - xmin) / ds_elevation.RasterXSize
    yres = (ymin - ymax) / ds_elevation.RasterYSize
    xform = xmin, xres, 0, ymax, 0, yres
    
    ds_elevation.SetGeoTransform(xform)
    ds_elevation.SetProjection(webmerc_sref.ExportToWkt())
    
    print ds_elevation
    
    for ds_in in srtm1_datasources(coord):
        gdal.ReprojectImage(ds_in, ds_elevation, ds_in.GetProjection(), ds_elevation.GetProjection(), gdal.GRA_Cubic)
        ds_in.FlushCache()
    
    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    
    cell = ds_elevation.ReadAsArray(0, 0, width, height)
    
    ds_elevation.FlushCache()
    
    print cell.shape
    
    z, scale = 1.0, 1.0
    
    window = [z * cell[row:(row + cell.shape[0] - 2), col:(col + cell.shape[1] - 2)]
              for (row, col)
              in product(range(3), range(3))]
    
    print 'calculating slope and aspect...'
    
    x = ((window[0] + window[3] + window[3] + window[6]) \
       - (window[2] + window[5] + window[5] + window[8])) \
      / (8.0 * xres * scale);
    
    y = ((window[6] + window[7] + window[7] + window[8]) \
       - (window[0] + window[1] + window[1] + window[2])) \
      / (8.0 * yres * scale);

    # in radians, from 0 to pi/2
    slope = pi/2 - numpy.arctan(numpy.sqrt(x*x + y*y))
    
    # in radians counterclockwise, from -pi at north back to pi
    aspect = numpy.arctan2(x, y)
    
    #
    # store slope and aspect mapped into 8-bit range as JPEG to save space
    #
    slope_data = (0xFF * numpy.sin(slope + pi/2)).astype(numpy.uint8)
    ds_slope = driver.Create('slope.tif', width, height, 1, gdal.GDT_Byte, ['COMPRESS=JPEG', 'JPEG_QUALITY=90'])
    ds_slope.WriteRaster(0, 0, slope.shape[0], slope.shape[1], slope_data.tostring())
    ds_slope.FlushCache()
    
    aspect_data = (0xFF * (aspect/pi + 1)/2).astype(numpy.uint8)
    ds_aspect = driver.Create('aspect.tif', width, height, 1, gdal.GDT_Byte, ['COMPRESS=JPEG', 'JPEG_QUALITY=90'])
    ds_aspect.WriteRaster(0, 0, aspect.shape[0], aspect.shape[1], aspect_data.tostring())
    ds_aspect.FlushCache()
    
    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    
    print 'calculating shade...'
    
    azimuth, altitude = 315.0, 45.0
    
    deg2rad = pi / 180.0
    
    shaded = sin(altitude * deg2rad) * numpy.sin(slope) \
           + cos(altitude * deg2rad) * numpy.cos(slope) \
           * numpy.cos((azimuth - 90.0) * deg2rad - aspect);
    
    shaded_data = (0xFF * shaded).astype(numpy.uint8)
    ds_shaded = driver.Create('shaded.tif', width, height, 1, gdal.GDT_Byte)
    ds_shaded.WriteRaster(0, 0, shaded.shape[0], shaded.shape[1], shaded_data.tostring(), buf_type=gdal.GDT_Byte)
    ds_shaded.FlushCache()
    
    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    
    print 'calculating shade again...'
    
    ds_slope = gdal.Open('slope.tif')
    slope_data = ds_slope.ReadAsArray(0, 0, width, height).astype(numpy.float32)
    slope = pi/2 - numpy.arcsin(slope_data / 0xFF)
    
    ds_aspect = gdal.Open('aspect.tif')
    aspect_data = ds_aspect.ReadAsArray(0, 0, width, height).astype(numpy.float32)
    aspect = (2 * aspect_data/0xFF - 1) * pi
    
    deg2rad = pi / 180.0
    
    shaded = sin(altitude * deg2rad) * numpy.sin(slope) \
           + cos(altitude * deg2rad) * numpy.cos(slope) \
           * numpy.cos((azimuth - 90.0) * deg2rad - aspect);
    
    shaded_data = (0xFF * shaded).astype(numpy.uint8)
    ds_shaded = driver.Create('shaded-j90.tif', width, height, 1, gdal.GDT_Byte)
    ds_shaded.WriteRaster(0, 0, shaded.shape[0], shaded.shape[1], shaded_data.tostring(), buf_type=gdal.GDT_Byte)
    ds_shaded.FlushCache()
