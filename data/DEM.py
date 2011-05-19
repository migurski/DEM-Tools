""" Starting point for DEM retrieval utilities.
"""
from sys import stderr
from math import floor
from os import unlink, close, write, mkdir, chmod
from os.path import basename, exists, isdir, join
from httplib import HTTPConnection
from urlparse import urlparse
from tempfile import mkstemp
from zipfile import ZipFile
from hashlib import md5

from ModestMaps.Core import Coordinate
from TileStache.Geography import SphericalMercator

from osgeo import gdal, osr

source_dir = 'source'

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

def srtm1_tiles(minlon, minlat, maxlon, maxlat):
    """ Generate a list of southwest (lon, lat) for 1-degree tiles of SRTM1 data.
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
    
    dem_dir = md5(url).hexdigest()[:4]
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
        dsfile = open(dem_path, 'w')
        dsfile.write(zipfile.read(zipfile.namelist()[0]))
        
        chmod(dem_path, 0666)
    
    finally:
        unlink(zip_path)

    #
    # The file better exist locally now
    #
    return gdal.Open(dem_path, gdal.GA_ReadOnly)

def tile_bounds(coord, sref, buffer=0):
    """ Retrieve bounding box of a tile coordinate in specified projection.
    
        If provided, buffer by a given number of pixels (assumes 256x256 tiles).
    """
    gutter = buffer and (float(buffer) / 256) or 0
    
    # buffer the tile a bit to add a bit more padding
    ul = webmerc_proj.coordinateProj(coord.left(gutter).up(gutter))
    lr = webmerc_proj.coordinateProj(coord.down(1 + gutter).right(1 + gutter))
    
    cs2cs = osr.CoordinateTransformation(webmerc_sref, sref)
    
    xmin, ymax, z = cs2cs.TransformPoint(ul.x, ul.y)
    xmax, ymin, z = cs2cs.TransformPoint(lr.x, lr.y)
    
    return xmin, ymin, xmax, ymax

def srtm1_datasources(coord):
    """ Retrieve a list of SRTM1 datasources overlapping the tile coordinate.
    """
    xmin, ymin, xmax, ymax = tile_bounds(coord, srtm1_sref, 4)
    
    return [srtm1_datasource(lat, lon)
            for (lon, lat)
            in srtm1_tiles(xmin, ymin, xmax, ymax)]

if __name__ == '__main__':

    coord = Coordinate(1582, 659, 12)

    #print srtm1_region(37.854525, -121.999741)
    
    xmin, ymin, xmax, ymax = tile_bounds(coord, webmerc_sref, 4)
    
    driver = gdal.GetDriverByName('GTiff')
    ds_out = driver.Create('out.tif', 256 + 8, 256 + 8, 1, gdal.GDT_Float32)
    
    xform = xmin, ((xmax - xmin) / ds_out.RasterXSize), 0, \
            ymax, 0, ((ymin - ymax) / ds_out.RasterYSize)
    
    ds_out.SetGeoTransform(xform)
    ds_out.SetProjection(webmerc_sref.ExportToWkt())
    
    print ds_out
    
    for ds_in in srtm1_datasources(coord):
        print 'go...'
        gdal.ReprojectImage(ds_in, ds_out, ds_in.GetProjection(), ds_out.GetProjection(), gdal.GRA_Cubic)
        ds_in.FlushCache()
    
    ds_out.FlushCache()
