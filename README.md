# river_data

The idea is to download River Dee data from the near realtime API (EA and NRW) to accumulate yearly files of data. Not all stations allow access to historical data, so the aim here is to accumate some.

At present the idea is to launch a weekly script to obtain a week of data up to yesterday. This is stored in a sqlite database and converted to a JSON file.

Next steps are to:
* manage these files so they don't get combersome
* to create yearly netCDF files
* Create a method to check on the data.
