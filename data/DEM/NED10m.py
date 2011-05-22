""" Starting point for DEM retrieval utilities.
"""
from sys import stderr
from math import floor, ceil, log
from os import unlink, close, write, mkdir, chmod
from os.path import basename, exists, isdir, join
from ftplib import FTP, error_perm
from urlparse import urlparse
from tempfile import mkstemp
from hashlib import md5

from TileStache.Geography import SphericalMercator

from osgeo import gdal, osr

source_dir = 'source'
ideal_zoom = 15 ### log(3 * 3600*360 / 256) / log(2) # ~13.9

osr.UseExceptions() # <-- otherwise errors will be silent and useless.

sref = osr.SpatialReference()
sref.ImportFromProj4('+proj=longlat +ellps=GRS80 +datum=NAD83 +no_defs')

def quads(minlon, minlat, maxlon, maxlat):
    """ Generate a list of northwest (lon, lat) for 1-degree quads of NED 10m data.
    """
    lon = floor(minlon)
    while lon <= maxlon:
    
        lat = ceil(maxlat)
        while lat >= minlat:
        
            yield lon, lat
        
            lat -= 1
    
        lon += 1

def datasource(lat, lon):
    """ Return a gdal datasource for a NED 10m lat, lon corner.
    
        If it doesn't already exist locally in source_dir, grab a new one.
    """
    #
    # Create a URL
    #

    fmt = 'ftp://projects.atlas.ca.gov/pub/ned/%d%d/float/floatn%dw%d_13.*'
    url = fmt % (abs(lat), abs(lon), abs(lat), abs(lon))
    
    #
    # Create a local filepath
    #
    s, host, path, p, q, f = urlparse(url)
    
    local_dir = md5(url).hexdigest()[:2]
    local_dir = join(source_dir, local_dir)
    
    local_base = join(local_dir, basename(path)[:-2])
    local_path = local_base + '.flt'
    local_none = local_base + '.404'
    
    #
    # Check if the file exists locally
    #
    if exists(local_path):
        return gdal.Open(local_path, gdal.GA_ReadOnly)

    if exists(local_none):
        return None

    if not exists(local_dir):
        mkdir(local_dir)
        chmod(local_dir, 0777)
    
    assert isdir(local_dir)
    
    #
    # Grab a fresh remote copy
    #
    print >> stderr, 'Retrieving', url, 'in DEM.NED10m.datasource().'
    
    conn = FTP(host)
    conn.login()
    
    for ext in ('.prj', '.hdr', '.flt'):
        remote_path = path[:-2] + ext
        local_path = local_base + ext
        local_file = open(local_path, 'wb')
        
        try:
            conn.retrbinary('RETR ' + remote_path, local_file.write)
        except error_perm:
            # permanent error, for example 550 when there's no file
            print >> open(local_none, 'w'), url
            return None
    
        print >> stderr, '  ', remote_path, '-->', local_path
        
        if ext == '.hdr':
            # GDAL needs some extra hints to understand the raw float data
            print >> local_file, 'nbits 32'
            print >> local_file, 'pixeltype float'
        
        local_file.close()

    conn.quit()
    
    #
    # The file better exist locally now
    #
    return gdal.Open(local_path, gdal.GA_ReadOnly)

def datasources(minlon, minlat, maxlon, maxlat):
    """ Retrieve a list of SRTM1 datasources overlapping the tile coordinate.
    """
    lonlats = quads(minlon, minlat, maxlon, maxlat)
    sources = [datasource(lat, lon) for (lon, lat) in lonlats]
    return [ds for ds in sources if ds]
