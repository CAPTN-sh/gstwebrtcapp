"""
pipelines.py

Description: A header with default GStreamer pipelines for the WebRTC applications.

Author:
    - Nikita Smirnov <nsm@informatik.uni-kiel.de>

License:
    GPLv3 License

"""

# H264/H265 codecs
BIN_H264_IN_H264_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph264depay ! h264parse ! avdec_h264 ! queue ! 
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !
    capsfilter name=raw_capsfilter caps=video/x-raw !
    x264enc name=encoder tune=zerolatency speed-preset=ultrafast threads=4 key-int-max=2560 b-adapt=false cabac=1 vbv-buf-capacity=120 ! queue !
    rtph264pay name=payloader auto-header-extension=true aggregate-mode=zero-latency config-interval=1 mtu=1200 !
    capsfilter name=payloader_capsfilter caps="application/x-rtp, media=(string)video, clock-rate=(int)90000, encoding-name=(string)H264, payload=(int)126" ! queue ! webrtc.
'''

BIN_H264_CUDA_IN_H264_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph264depay ! h264parse ! nvh264dec ! queue ! 
    videoconvertscale n-threads=4 ! videorate skip-to-first=true ! 
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    x264enc name=encoder tune=zerolatency speed-preset=ultrafast threads=4 key-int-max=2560 b-adapt=false cabac=1 vbv-buf-capacity=120 ! queue !
    rtph264pay name=payloader auto-header-extension=true aggregate-mode=zero-latency config-interval=1 mtu=1200 ! 
    capsfilter name=payloader_capsfilter caps="application/x-rtp, media=(string)video, clock-rate=(int)90000, encoding-name=(string)H264, payload=(int)126" ! queue ! webrtc.
'''

BIN_H264_CUDA_IN_H264_CUDA_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=100 drop-on-latency=true ! queue ! rtph264depay ! h264parse ! nvh264dec ! queue ! 
    videoconvertscale n-threads=4 ! videorate skip-to-first=true ! 
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    cudaupload !  
    nvh264enc name=encoder gop-size=60 preset=low-latency-hq rc-mode=cbr temporal-aq=true zerolatency=true tune=ultra-low-latency ! queue ! 
    rtph264pay name=payloader aggregate-mode=zero-latency config-interval=1 mtu=1200 ! 
    capsfilter name=payloader_capsfilter caps="application/x-rtp, media=(string)video, clock-rate=(int)90000, encoding-name=(string)H264, payload=(int)126" ! queue ! webrtc.
'''

# h265 input: e.g. for reolink cameras that stream 4k in hevc
BIN_H265_IN_H264_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph265depay ! h265parse ! avdec_h265 ! queue !
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    x264enc name=encoder tune=zerolatency speed-preset=ultrafast threads=4 key-int-max=2560 b-adapt=false cabac=1 vbv-buf-capacity=120 ! queue ! 
    rtph264pay name=payloader auto-header-extension=true aggregate-mode=zero-latency config-interval=1 mtu=1200 ! 
    capsfilter name=payloader_capsfilter caps="application/x-rtp, media=(string)video, clock-rate=(int)90000, encoding-name=(string)H264, payload=(int)126, rtcp-fb-goog-remb=(boolean)true, rtcp-fb-transport-cc=(boolean)true" ! webrtc.
'''

BIN_H265_CUDA_IN_H264_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=30 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=100 drop-on-latency=true ! queue ! rtph265depay ! h265parse ! nvh265dec ! queue !
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    x264enc name=encoder tune=zerolatency speed-preset=ultrafast threads=4 key-int-max=2560 b-adapt=false cabac=1 vbv-buf-capacity=120 ! queue ! 
    rtph264pay name=payloader auto-header-extension=true aggregate-mode=zero-latency config-interval=1 mtu=1200 ! 
    capsfilter name=payloader_capsfilter caps="application/x-rtp, media=(string)video, clock-rate=(int)90000, encoding-name=(string)H264, payload=(int)126, rtcp-fb-goog-remb=(boolean)true, rtcp-fb-transport-cc=(boolean)true" ! webrtc.
'''

BIN_H265_CUDA_IN_H264_CUDA_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=100 drop-on-latency=true ! queue ! rtph265depay ! h265parse ! nvh265dec ! queue ! 
    videoconvertscale n-threads=4 ! videorate skip-to-first=true ! queue !
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    cudaupload ! 
    nvh264enc name=encoder gop-size=60 strict-gop=true preset=p1 rc-mode=cbr temporal-aq=true zerolatency=true tune=ultra-low-latency multi-pass=2 !
    rtph264pay name=payloader aggregate-mode=zero-latency config-interval=1 mtu=1200 ! 
    capsfilter name=payloader_capsfilter caps="application/x-rtp, media=(string)video, clock-rate=(int)90000, encoding-name=(string)H264, payload=(int)126" ! webrtc.
'''

# NOTE: Chrome does not play HEVC, a black screen
BIN_H264_IN_H265_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph264depay ! h264parse ! avdec_h264 ! queue ! 
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    x265enc name=encoder key-int-max=2560 speed-preset=superfast tune=zerolatency speed-preset=ultrafast ! h265parse ! queue !
    rtph265pay name=payloader auto-header-extension=true config-interval=1 mtu=1200 ! 
    capsfilter name=payloader_capsfilter ! queue ! webrtc.
'''

BIN_H264_CUDA_IN_H265_CUDA_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph264depay ! h264parse ! nvh264dec ! queue ! 
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !  
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    cudaupload ! 
    nvh265enc name=encoder gop-size=60 strict-gop=true preset=low-latency-hq rc-mode=cbr temporal-aq=true zerolatency=true tune=ultra-low-latency ! h265parse ! queue ! 
    rtph265pay name=payloader auto-header-extension=true config-interval=1 mtu=1200 ! 
    capsfilter name=payloader_capsfilter ! queue max-size-buffers=2 leaky=downstream ! webrtc.
'''

BIN_H265_CUDA_IN_H265_CUDA_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph265depay ! h265parse ! nvh265dec ! queue ! 
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !  
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    cudaupload ! 
    nvh265enc name=encoder gop-size=60 strict-gop=true preset=low-latency-hq rc-mode=cbr temporal-aq=true zerolatency=true tune=ultra-low-latency ! h265parse ! queue ! 
    rtph265pay name=payloader auto-header-extension=true config-interval=1 mtu=1200 ! 
    capsfilter name=payloader_capsfilter ! queue max-size-buffers=2 leaky=downstream ! webrtc.
'''

# VP* codecs
BIN_H264_IN_VP8_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph264depay ! h264parse ! avdec_h264 ! queue ! 
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    vp8enc name=encoder deadline=1 end-usage=cbr buffer-initial-size=100 buffer-optimal-size=120 buffer-size=150 max-intra-bitrate=250 multipass-mode=first-pass error-resilient=default lag-in-frames=0 threads=16 ! queue !
    rtpvp8pay name=payloader auto-header-extension=true picture-id-mode=15-bit mtu=1200 ! 
    capsfilter name=payloader_capsfilter ! queue ! webrtc.
'''

BIN_H265_IN_VP8_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph265depay ! h265parse ! avdec_h265 ! queue ! 
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    vp8enc name=encoder deadline=1 end-usage=cbr buffer-initial-size=100 buffer-optimal-size=120 buffer-size=150 max-intra-bitrate=250 multipass-mode=first-pass error-resilient=default lag-in-frames=0 threads=16 ! queue !
    rtpvp8pay name=payloader auto-header-extension=true picture-id-mode=15-bit mtu=1200 ! 
    capsfilter name=payloader_capsfilter ! queue ! webrtc.
'''

BIN_H264_CUDA_IN_VP8_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph264depay ! h264parse ! nvh264dec ! queue !
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    vp8enc name=encoder deadline=1 end-usage=cbr buffer-initial-size=100 buffer-optimal-size=120 buffer-size=150 max-intra-bitrate=250 multipass-mode=first-pass error-resilient=default lag-in-frames=0 threads=16 cpu-used=-16 ! queue !
    rtpvp8pay name=payloader auto-header-extension=true picture-id-mode=15-bit mtu=1200 ! 
    capsfilter name=payloader_capsfilter ! queue ! webrtc.
'''

BIN_H265_CUDA_IN_VP8_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph265depay ! h265parse ! nvh265dec ! queue !
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    vp8enc name=encoder deadline=1 end-usage=cbr buffer-initial-size=100 buffer-optimal-size=120 buffer-size=150 max-intra-bitrate=250 multipass-mode=first-pass error-resilient=default lag-in-frames=0 threads=16 cpu-used=-16 ! queue !
    rtpvp8pay name=payloader auto-header-extension=true picture-id-mode=15-bit mtu=1200 ! 
    capsfilter name=payloader_capsfilter ! queue ! webrtc.
'''

BIN_H264_IN_VP9_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph264depay ! h264parse ! avdec_h264 ! queue ! 
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    vp9enc name=encoder deadline=1 keyframe-max-dist=2000 keyframe-mode=disabled end-usage=cbr buffer-initial-size=100 buffer-optimal-size=120 buffer-size=150 max-intra-bitrate=250 multipass-mode=first-pass error-resilient=default lag-in-frames=0 threads=16 cpu-used=-16 ! queue !
    rtpvp9pay name=payloader auto-header-extension=true picture-id-mode=15-bit mtu=1200 ! 
    capsfilter name=payloader_capsfilter ! queue ! webrtc.
'''

BIN_H264_CUDA_IN_VP9_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph264depay ! h264parse ! nvh264dec ! queue ! 
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    vp9enc name=encoder deadline=1 keyframe-max-dist=2000 keyframe-mode=disabled end-usage=cbr buffer-initial-size=100 buffer-optimal-size=120 buffer-size=150 max-intra-bitrate=250 multipass-mode=first-pass error-resilient=default lag-in-frames=0 threads=16 cpu-used=-16 ! queue !
    rtpvp9pay name=payloader auto-header-extension=true picture-id-mode=15-bit mtu=1200 ! 
    capsfilter name=payloader_capsfilter ! queue ! webrtc.
'''

BIN_H265_IN_VP9_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph265depay ! h265parse ! avdec_h265 ! queue ! 
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    vp9enc name=encoder deadline=1 keyframe-max-dist=2000 keyframe-mode=disabled end-usage=cbr buffer-initial-size=100 buffer-optimal-size=120 buffer-size=150 max-intra-bitrate=250 multipass-mode=first-pass error-resilient=default lag-in-frames=0 threads=16 cpu-used=-16 ! queue !
    rtpvp9pay name=payloader auto-header-extension=true picture-id-mode=15-bit mtu=1200 ! 
    capsfilter name=payloader_capsfilter ! queue ! webrtc.
'''

BIN_H265_CUDA_IN_VP9_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph265depay ! h265parse ! nvh265dec ! queue ! 
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    vp9enc name=encoder deadline=1 keyframe-max-dist=2000 keyframe-mode=disabled end-usage=cbr buffer-initial-size=100 buffer-optimal-size=120 buffer-size=150 max-intra-bitrate=250 multipass-mode=first-pass error-resilient=default lag-in-frames=0 threads=16 cpu-used=-16 ! queue !
    rtpvp9pay name=payloader auto-header-extension=true picture-id-mode=15-bit mtu=1200 ! 
    capsfilter name=payloader_capsfilter ! queue ! webrtc.
'''

# AV1 codec
# NOTE: av1enc seems to be a problem so far
BIN_H264_IN_AV1_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph264depay ! h264parse ! avdec_h264 ! queue ! 
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !
    capsfilter name=raw_capsfilter caps=video/x-raw !
    av1enc name=encoder usage-profile=realtime end-usage=cbr keyframe-max-dist=32 threads=16 ! av1parse ! queue !
    rtpav1pay name=payloader auto-header-extension=true mtu=1200 ! 
    capsfilter name=payloader_capsfilter ! queue ! webrtc.
'''

BIN_H264_CUDA_IN_AV1_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph264depay ! h264parse ! nvh264dec ! queue ! 
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    av1enc name=encoder usage-profile=realtime end-usage=cbr keyframe-max-dist=32 threads=16 ! av1parse ! queue !
    rtpav1pay name=payloader auto-header-extension=true mtu=1200 ! 
    capsfilter name=payloader_capsfilter ! queue ! webrtc.
'''

BIN_H265_IN_AV1_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph265depay ! h265parse ! avdec_h265 ! queue ! 
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    av1enc name=encoder usage-profile=realtime end-usage=cbr keyframe-max-dist=32 threads=16 ! av1parse ! queue !
    rtpav1pay name=payloader auto-header-extension=true mtu=1200 ! 
    capsfilter name=payloader_capsfilter ! queue ! webrtc.
'''

BIN_H265_CUDA_IN_AV1_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph265depay ! h265parse ! nvh265dec ! queue ! 
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    av1enc name=encoder usage-profile=realtime end-usage=cbr keyframe-max-dist=32 threads=16 ! av1parse ! queue !
    rtpav1pay name=payloader auto-header-extension=true mtu=1200 ! 
    capsfilter name=payloader_capsfilter ! queue ! webrtc.
'''

BIN_H264_CUDA_IN_AV1_CUDA_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=40 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph264depay ! h264parse ! nvh264dec ! queue ! 
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    cudaupload !
    nvav1enc name=encoder rc-mode=cbr zerolatency=true tune=ultra-low-latency gop_size=60 ! av1parse ! queue ! 
    rtpav1pay name=payloader mtu=1200 ! 
    capsfilter name=payloader_capsfilter ! queue ! webrtc.
'''

BIN_H265_CUDA_IN_AV1_CUDA_OUT_PIPELINE = '''
    webrtcbin name=webrtc latency=200 bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph265depay ! h265parse ! nvh265dec ! queue ! 
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !
    capsfilter name=raw_capsfilter caps=video/x-raw ! 
    cudaupload !
    nvav1enc name=encoder rc-mode=cbr zerolatency=true tune=ultra-low-latency gop_size=60 ! av1parse ! queue ! 
    rtpav1pay name=payloader mtu=1200 ! 
    capsfilter name=payloader_capsfilter ! queue ! webrtc.
'''

SINK_H264_IN_H264_OUT_PIPELINE = '''
    webrtcsink name=ws signaller::uri=ws://127.0.0.1:8443 do-retransmission=true do-fec=true congestion-control=disabled
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph264depay ! h264parse ! avdec_h264 ! queue !
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !
    video/x-raw,framerate=60/1 ! queue ! ws.
'''

SINK_H264_CUDA_IN_H264_OUT_PIPELINE = '''
    webrtcsink name=ws signaller::uri=ws://127.0.0.1:8443 do-retransmission=true do-fec=true congestion-control=disabled
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph264depay ! h264parse ! nvh264dec ! queue !
    videoconvertscale n-threads=4 ! videorate skip-to-first=true !
    video/x-raw,framerate=60/1 ! queue ! ws.
'''

SINK_H264_CUDA_IN_H264_CUDA_OUT_PIPELINE = '''
    webrtcsink name=ws signaller::uri=ws://127.0.0.1:8443 do-retransmission=true do-fec=true congestion-control=disabled
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph264depay ! h264parse ! nvh264dec ! queue !
    videoconvertscale n-threads=4 ! videorate skip-to-first=true ! 
    cudaupload !   
    video/x-raw(memory:CUDAMemory),framerate=60/1 ! queue ! ws.
'''

SINK_H265_CUDA_IN_H264_OUT_PIPELINE = '''
    webrtcsink name=ws signaller::uri=ws://127.0.0.1:8443 do-retransmission=true do-fec=true congestion-control=disabled
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph265depay ! h265parse ! nvh265dec ! queue !
    videoconvertscale n-threads=4 ! videorate skip-to-first=true ! 
    video/x-raw,framerate=60/1 ! queue ! ws.
'''

SINK_H265_IN_H264_CUDA_OUT_PIPELINE = '''
    webrtcsink name=ws signaller::uri=ws://127.0.0.1:8443 do-retransmission=true do-fec=true congestion-control=disabled
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph265depay ! h265parse ! avdec_h265 ! queue !
    videoconvertscale n-threads=4 ! videorate skip-to-first=true ! 
    cudaupload !   
    video/x-raw(memory:CUDAMemory),framerate=60/1 ! queue ! ws.
'''

SINK_H265_CUDA_IN_H264_CUDA_OUT_PIPELINE = '''
    webrtcsink name=ws signaller::uri=ws://127.0.0.1:8443 do-retransmission=true do-fec=true congestion-control=disabled
    rtspsrc name=source location=rtsp://10.10.3.254:554 latency=200 drop-on-latency=true ! queue ! rtph265depay ! h265parse ! nvh265dec ! queue !
    videoconvertscale n-threads=4 ! videorate skip-to-first=true ! 
    cudaupload ! 
    video/x-raw(memory:CUDAMemory),framerate=60/1 ! queue ! ws.
'''


def get_pipeline_by_specs(type: str, codec_in: str, codec_out: str, cuda_in: bool, cuda_out: bool) -> str:
    if type not in ["sink", "ahoy"]:
        raise ValueError(f"get_pipeline_by_specs: unsupported type: {type}")
    if codec_in not in ["h264", "h265"]:
        raise ValueError(f"get_pipeline_by_specs: unsupported codec_in: {codec_in}")
    if codec_out not in ["h264", "h265", "vp8", "vp9", "av1"]:
        raise ValueError(f"get_pipeline_by_specs: unsupported codec_out: {codec_out}")
    type_str = "BIN" if type == "ahoy" else "SINK"
    cuda_in_str = "_CUDA" if cuda_in or cuda_out else ""
    cuda_out_str = "_CUDA" if cuda_out else ""
    codec_out_str = codec_out.upper() if type == "ahoy" else "H264"
    pipeline_name = f"{type_str}_{codec_in.upper()}{cuda_in_str}_IN_{codec_out_str}{cuda_out_str}_OUT_PIPELINE"
    pipeline = globals().get(pipeline_name, None)
    if pipeline is None:
        raise ValueError(f"get_pipeline_by_specs: built pipeline name not found: {pipeline_name}")
    return pipeline.replace("\n", "")
