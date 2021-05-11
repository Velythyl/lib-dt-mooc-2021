import os
import re
import struct

import torch
from dt_data_api import DataClient

try:
    from dt_mooc.colab import ColabProgressBar
    _pbar = ColabProgressBar()
    monitor = _pbar.transfer_monitor
except ImportError:
    from dt_mooc.utils import plain_progress_monitor as monitor

from dt_mooc.utils import *

class Storage:

    def __init__(self, token: str):
        self._client = DataClient(token)
        self._space = self._client.storage("user")
        self._folder = 'courses/mooc/2021/data'

    @staticmethod
    def export_model(name: str, model: torch.nn.Module, input: torch.Tensor):
        if re.match('^[0-9a-zA-Z-_.]+$', name) is None:
            raise ValueError("The model name can only container letters, numbers and these "
                             "symbols '.,-,_'")
        # ---
        # export the model
        torch.onnx.export(model,  # model being run
                          input,  # model input (or a tuple for multiple inputs)
                          f"{name}.onnx",
                          # where to save the model (can be a file or file-like object)
                          export_params=True,
                          # store the trained parameter weights inside the model file
                          opset_version=10,  # the ONNX version to export the model to
                          do_constant_folding=True,
                          # whether to execute constant folding for optimization
                          input_names=['input'],  # the model's input names
                          output_names=['output'],  # the model's output names
                          dynamic_axes={'input': {0: 'batch_size'},  # variable lenght axes
                                        'output': {0: 'batch_size'}})

    def upload_yolov5(self, destination_name, pt_model, pt_weights_path): # might want to use template pattern if we want to make a bunch of these
        wts_path = pt_weights_path + '.wts'

        # STEP 1: CONVERT TO WTS

        # Get model
        device = select_device('cpu')
        model = pt_model.to(device).float()  # load to FP32
        model.eval()

        # Convert
        with open(wts_path, 'w') as f:
            f.write('{}\n'.format(len(model.state_dict().keys())))
            for k, v in model.state_dict().items():
                vr = v.reshape(-1).cpu().numpy()
                f.write('{} {} '.format(k, len(vr)))
                for vv in vr:
                    f.write(' ')
                    f.write(struct.pack('>f', float(vv)).hex())
                f.write('\n')

        # STEP 2: WRITE HASH
        self.hash(wts_path)
        hash_path = wts_path+".sha256"  # todo string duplication, might want to move this to a string global

        # STEP 2: UPLOAD BOTH .pt AND .wts
        self._upload(destination_name, [pt_weights_path, wts_path, hash_path])

    def hash(self, filepath, write=True):    # not a private function: we'll need it on the JN!
        f"""
        Shamelessly stolen from https://stackoverflow.com/a/62214783/11296012
        
        :param filepath: hashes this file
        :return: writes hash to {filepath}.hash and returns the hash
        """
        import hashlib
        import mmap

        hash_filepath = filepath + '.sha256'

        h = hashlib.sha256()
        with open(filepath, 'rb') as f:
            with mmap.mmap(f.fileno(), 0, prot=mmap.PROT_READ) as mm:
                h.update(mm)
        h = h.hexdigest()

        if write:
            with open(hash_filepath, "w") as f:
                f.write(h)

        return h

    def _upload(self, new_filename, files):
        try:    # promote to iterable if it isn't one
            iter(files)
        except TypeError:
            files = [files]

        for file in files:  # for each file
            dir, old_filename, ext = get_dfe(file)  # split into dir, filename, extension

            destination = os.path.join(self._folder, 'nn_models', f"{new_filename}.{ext}")  # means that we rename but keep the extension!

            print(f'Uploading file `{old_filename+"."+ext}`...')
            handler = self._space.upload(file, destination)
            handler.register_callback(monitor)
            # wait for the upload to finish
            handler.join()  # todo can probably not join after every file, will clean this up if we need a faster version
            print(f'\nFile `{old_filename+"."+ext}` successfully uploaded! It will now found at `{destination}`.')


    def upload_model(self, name: str, model: torch.nn.Module, input: torch.Tensor):
        # export the model
        self.export_model(name, model, input)
        # define source/destination paths
        source = f"{name}.onnx"
        destination = os.path.join(self._folder, 'nn_models', f"{name}.onnx")
        # upload the model
        print(f'Uploading model `{name}`...')
        handler = self._space.upload(source, destination)
        handler.register_callback(monitor)
        # wait for the upload to finish
        handler.join()
        print(f'\nModel successfully uploaded!')

if __name__ == "__main__":
    token = sys.argv[1]
    pt = sys.argv[2]
    store = Storage(token)

    import sys

    sys.path.insert(0, './yolov5')
    model = torch.load(pt, map_location=select_device("cpu"))['model'].float()  # load to FP32
    model.to(select_device("cpu")).eval()

    store.upload_yolov5("yolov5", model, pt)