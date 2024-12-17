# Installation
install gst-shark and read the tutorial on how to use it: [gst-shark](https://developer.ridgerun.com/wiki/index.php/GstShark)

by [installing](https://developer.ridgerun.com/wiki/index.php/GstShark_-_Getting_Started) it with the autogen in the docker container, change the --libdir argument from  `/usr/lib/x86_64-linux-gnu/` to `/usr/local/lib/x86_64-linux-gnu/`

unset env variables after the installation:
```bash
unset GST_SHARK_LOCATION && unset GST_SHARK_CTF_DISABLE
```

# Usage
The tracers work by redirecting the output pipes directly to the log files to avoid working with the CTF traces:
```bash
GST_DEBUG="GST_TRACER:7" GST_SHARK_FILE_BUFFERING=0  GST_TRACERS="interlatency;proctime;framerate;scheduletime;queuelevel" <script> 2> > (tee datastream.log > metadata.log)
```

Then use datastream.log to generate the report. The parser is adapted to the file dump of the gst-shark traces and produces a csv file for each tracer in the same :
```bash
python parser.py -l <path/to/datastream.log> -o <path/to/output/folder>
```

Go to the outputGenerate plots with e.g. the following command when the output folder above was not specified and defaulted to the current directory:
```bash
python plotter.py -f "interlatency.csv,proctime.csv,scheduletime.csv,queuelevel.csv" -t "interlatency,proctime,scheduletime,queuelevel" -v "time,time,time,size_time" -m 5 -s
```

or if for the same tracer but different values:
```bash
python plotter.py -f "queuelevel.csv" -t "queuelevel" -v "size_time,max_size_time,size_buffers,max_size_buffers" -m 5 -st -s
```

consult either tutorial or `TRACER_ATTRIBUTES` in the `parser.py` for the available values for the `-t` and `-v` arguments. `-m` argument is used to set the minimum number of values guarantted to be plotted in the same graph. `-s` argument is used to save the plots in the same directory as the csv files. `-st` argument is used to plot different values for the same tracer.

# Draw the pipeline
To draw the pipeline, one need to set the `is_graph` parameter in `GstWebRTCAppConfig` instance or in a yaml config for that to `True` and run the pipeline with `GST_DEBUG_DUMP_DOT_DIR=.` or any other directory. The pipeline will be dumped in the dot format in the specified directory.

To export it as an image, first install the graphviz package:
```bash
apt-get install -y graphviz
```
and then run the following command to export the image:
```bash
 dot -Tpng <path/to/pipeline.dot-file> -o <path/to/output.png-file>
```

# Author
Nikita Smirnov, [mailto](mailto:nikita.smirnov@cs.uni-kiel.de)