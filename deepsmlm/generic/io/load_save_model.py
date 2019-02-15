import torch

from deepsmlm.neuralfitter.model import DeepSLMN


class LoadSaveModel:
    def __init__(self, output_file, cuda, input_file=None):
        self.warmstart_file = input_file
        self.output_file = output_file
        self.cuda = cuda

    def load_init(self, cuda=torch.cuda.is_available()):
        model = DeepSLMN()

        if self.warmstart_file is None:
            model.weight_init()
            print('Model initialised randomly.')
        else:

            if cuda:
                model.load_state_dict(torch.load(self.warmstart_file))
            else:
                model.load_state_dict(torch.load(self.warmstart_file, map_location='cpu'))

            print('Loaded pretrained model: {}'.format(self.warmstart_file))
        model.eval()
        return model

    def save(self, model):
        torch.save(model.state_dict(), self.output_file)
        print('Saved model to file: {}'.format(self.output_file))
