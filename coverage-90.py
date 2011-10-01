""" Retrieve National Elevation Data for a given coverage area. Shells out to
    curl to perform file downloads of 1-deg quads of 3 arc second data sets.
"""
import json
from sys import stderr, stdout
from os import stat, unlink, rename
from shapely.geometry import Polygon
from subprocess import Popen

if __name__ == '__main__':

    #
    # The box of coverage area we're interested in.
    #
    n, w, s, e = 38.34, -123.07, 36.50, -121.07
    request = Polygon([(w, n), (e, n), (e, s), (w, s), (w, n)])

    #
    # Index of climate central coverage area to intersect with.
    #
    try:
        index = json.load(open('index.json', 'r'))
        polys = []

        for feature in index['features']:
            polygon = Polygon(*feature['geometry']['coordinates'])
            polys.append(polygon)

        #
        # Intersection of all requested area plus a little buffer.
        #
        coverage = reduce(lambda a, b: a.union(b), polys)
        coverage = coverage.intersection(request)
        coverage = coverage.buffer(.75, 5)
    except IOError, e:
        # No index.json file, just skip it
        coverage = request

    #
    # Catch 'em all.
    # For this data set, files are named by south-west corner of quad.
    #
    count = 0

    for lat in range(-90, 90):
        for lon in range(-180, 180):
            quad = Polygon([(lon, lat), (lon+1, lat), (lon+1, lat+1), (lon, lat+1), (lon, lat)])

            if quad.intersects(coverage):
                count += 1
                n, w = abs(lat), abs(lon)

                for region in ('Africa', 'Australia', 'Eurasia', 'Islands', 'North_America', 'South_America'):
                    url = 'http://dds.cr.usgs.gov/srtm/version2_1/SRTM3/%(region)s/N%(n)dW%(w)d.hgt.zip' % locals()
                    out = '90m/%(region)s-N%(n)dW%(w)d.hgt.zip' % locals()
                    keep = '90m/N%(n)dW%(w)d.hgt.zip' % locals()

                    print >> stderr, count, '--', url
                    curl = Popen(('curl', '-sL', url, '--output', out))
                    curl.wait()

                    # did we get a response that's too small?
                    if stat(out).st_size < 300:
                        unlink(out)
                        continue

                    rename(out, keep)
