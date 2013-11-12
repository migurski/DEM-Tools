""" Starting point for DEM retrieval utilities.
"""
from sys import stderr
from math import floor, ceil, log
from os import unlink, close, write, makedirs, chmod
from os.path import basename, exists, isdir, join
from tempfile import mkstemp, mkdtemp
from httplib import HTTPConnection
from shutil import move, rmtree
from urlparse import urlparse
from zipfile import ZipFile
from fnmatch import fnmatch
from hashlib import md5

from TileStache.Geography import SphericalMercator

from osgeo import gdal, osr

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

def datasource(lat, lon, source_dir):
    """ Return a gdal datasource for a NED 10m lat, lon corner.
    
        If it doesn't already exist locally in source_dir, grab a new one.
    """
    #
    # Create a URL - tdds3.cr.usgs.gov looks to be a redirect from
    # http://gisdata.usgs.gov/TDDS/DownloadFile.php?TYPE=ned3f_zip&FNAME=nxxwxx.zip
    #
    # FIXME for southern/western hemispheres
    fmt = 'http://tdds3.cr.usgs.gov/Ortho9/ned/ned_13/float/n%02dw%03d.zip'
    url = fmt % (abs(lat), abs(lon))
    
    #
    # Create a local filepath
    #
    s, host, path, p, q, f = urlparse(url)
    
    local_dir = md5(url).hexdigest()[:3]
    local_dir = join(source_dir, local_dir)
    
    local_base = join(local_dir, basename(path)[:-4])
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
        makedirs(local_dir)
        chmod(local_dir, 0777)
    
    assert isdir(local_dir)
    
    #
    # Grab a fresh remote copy
    #
    print >> stderr, 'Retrieving', url, 'in DEM.NED10m.datasource().'
    
    conn = HTTPConnection(host, 80)
    conn.request('GET', path)
    resp = conn.getresponse()
    
    if resp.status == 404:
        # we're probably outside the coverage area
        print >> open(local_none, 'w'), url
        return None
    
    assert resp.status == 200, (resp.status, resp.read())
    
    try:
        dirpath = mkdtemp(prefix='ned10m-')
        zippath = join(dirpath, 'dem.zip')

        zipfile = open(zippath, 'w')
        zipfile.write(resp.read())
        zipfile.close()

        zipfile = ZipFile(zippath)
        
        for name in zipfile.namelist():
            if fnmatch(name, '*/*/float*.???') and name[-4:] in ('.hdr', '.flt', '.prj'):
                local_file = local_base + name[-4:]

            elif fnmatch(name, '*/float*_13.???') and name[-4:] in ('.hdr', '.flt', '.prj'):
                local_file = local_base + name[-4:]

            elif fnmatch(name, '*/float*_13'):
                local_file = local_base + '.flt'

            else:
                # don't recognize the contents of this zip file
                continue
            
            zipfile.extract(name, dirpath)
            move(join(dirpath, name), local_file)
            
            if local_file.endswith('.hdr'):
                # GDAL needs some extra hints to understand the raw float data
                hdr_file = open(local_file, 'a')
                print >> hdr_file, 'nbits 32'
                print >> hdr_file, 'pixeltype float'
        
        #
        # The file better exist locally now
        #
        return gdal.Open(local_path, gdal.GA_ReadOnly)
    
    finally:
        rmtree(dirpath)

def datasources(minlon, minlat, maxlon, maxlat, source_dir):
    """ Retrieve a list of SRTM1 datasources overlapping the tile coordinate.
    """
    lonlats = quads(minlon, minlat, maxlon, maxlat)
    sources = [datasource(lat, lon, source_dir) for (lon, lat) in lonlats]
    return [ds for ds in sources if ds]
