#include <stdio.h>
#include <stdlib.h>
#include <vector>
#include <math.h>
#include <stdexcept>
#include <stdbool.h>

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>

// #include <cuda_runtime.h>

// ToDo: Namespace here did not work for a reason I don't yet understand.
#include "spline_psf_gpu.cuh"


namespace spc {
    extern "C" {
        #include "spline_psf.h"
    }
}

namespace spg = spline_psf_gpu;
namespace py = pybind11;

template <typename T>
class PSFWrapperBase {

    protected:
    
        T *psf;
        const int roi_size_x;
        const int roi_size_y;
        int frame_size_x;
        int frame_size_y;

        PSFWrapperBase(int rx, int ry) : roi_size_x(rx), roi_size_y(ry) { }
        PSFWrapperBase(int rx, int ry, int fx, int fy) : roi_size_x(rx), roi_size_y(ry), frame_size_x(fx), frame_size_y(fy) { }

};

class PSFWrapperCUDA : public PSFWrapperBase<spg::spline> {

    public:

        explicit PSFWrapperCUDA(int coeff_xsize, int coeff_ysize, int coeff_zsize, int roi_size_x_, int roi_size_y_,
            py::array_t<float, py::array::f_style | py::array::forcecast> coeff) : PSFWrapperBase{roi_size_x_, roi_size_y_} {

                psf = spg::d_spline_init(coeff.data(), coeff_xsize, coeff_ysize, coeff_zsize);

            }

        auto forward_psf(py::array_t<float, py::array::c_style | py::array::forcecast> x, 
                        py::array_t<float, py::array::c_style | py::array::forcecast> y, 
                        py::array_t<float, py::array::c_style | py::array::forcecast> z, 
                        py::array_t<float, py::array::c_style | py::array::forcecast> phot) -> py::array_t<float> {


            int n = x.size();  // number of ROIs
            py::array_t<float> h_rois(n * roi_size_x * roi_size_y);

            spg::forward_rois_host2host(psf, h_rois.mutable_data(), n, roi_size_x, roi_size_y, x.data(), y.data(), z.data(), phot.data());

            return h_rois;
        }

};

class PSFWrapperCPU : public PSFWrapperBase<spc::spline> {

    public:

        explicit PSFWrapperCPU(int coeff_xsize, int coeff_ysize, int coeff_zsize, int roi_size_x_, int roi_size_y_,
            py::array_t<float, py::array::f_style | py::array::forcecast> coeff) : PSFWrapperBase{roi_size_x_, roi_size_y_} {

                psf = spc::initSpline(coeff.data(), coeff_xsize, coeff_ysize, coeff_zsize);

            }

        auto forward_rois(py::array_t<float, py::array::c_style | py::array::forcecast> x, 
                          py::array_t<float, py::array::c_style | py::array::forcecast> y, 
                          py::array_t<float, py::array::c_style | py::array::forcecast> z, 
                          py::array_t<float, py::array::c_style | py::array::forcecast> phot) -> py::array_t<float> {

            const int n = x.size();
            py::array_t<float> h_rois(n * roi_size_x * roi_size_y);

            if (roi_size_x != roi_size_y) {
                throw std::invalid_argument("ROI size must be equal currently.");
            }

            spc::forward_rois(psf, h_rois.mutable_data(), n, roi_size_x, roi_size_y, x.data(), y.data(), z.data(), phot.data());

            return h_rois;
        }

        auto forward_frames(const int fx, const int fy,
                            py::array_t<int, py::array::c_style | py::array::forcecast> frame_ix,
                            const int n_frames,
                            py::array_t<float, py::array::c_style | py::array::forcecast> xr,
                            py::array_t<float, py::array::c_style | py::array::forcecast> yr,
                            py::array_t<float, py::array::c_style | py::array::forcecast> z,
                            py::array_t<int, py::array::c_style | py::array::forcecast> x_ix,
                            py::array_t<int, py::array::c_style | py::array::forcecast> y_ix,
                            py::array_t<float, py::array::c_style | py::array::forcecast> phot) -> py::array_t<float> {

            frame_size_x = fx;
            frame_size_y = fy;
            const int n_emitters = xr.size();
            py::array_t<float> h_frames(n_frames * frame_size_x * frame_size_y);
            // std::cout << "Size of Frames: " << h_frames.size() << "frame_si<< std::endl;

            spc::forward_frames(psf, h_frames.mutable_data(), frame_size_x, frame_size_y, n_emitters, roi_size_x, roi_size_y, 
                frame_ix.data(), xr.data(), yr.data(), z.data(), x_ix.data(), y_ix.data(), phot.data());

            return h_frames;
        }

};

PYBIND11_MODULE(spline_psf_cuda, m) {
    py::class_<PSFWrapperCUDA>(m, "PSFWrapperCUDA")
        .def(py::init<int, int, int, int, int, py::array_t<float>>())
        .def("forward_rois", &PSFWrapperCUDA::forward_psf);

    py::class_<PSFWrapperCPU>(m, "PSFWrapperCPU")
        .def(py::init<int, int, int, int, int, py::array_t<float>>())
        .def("forward_rois", &PSFWrapperCPU::forward_rois)
        .def("forward_frames", &PSFWrapperCPU::forward_frames);
}