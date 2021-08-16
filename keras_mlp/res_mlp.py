from tensorflow import keras

# import tensorflow as tf
import os


class ChannelAffine(keras.layers.Layer):
    def __init__(self, use_bias=True, weight_init_value=1, **kwargs):
        super(ChannelAffine, self).__init__(**kwargs)
        self.use_bias, self.weight_init_value = use_bias, weight_init_value
        self.ww_init = keras.initializers.Constant(weight_init_value) if weight_init_value != 1 else "ones"
        self.bb_init = "zeros"
        self.supports_masking = False

    def build(self, input_shape):
        self.ww = self.add_weight(name="weight", shape=(input_shape[-1]), initializer=self.ww_init, trainable=True)
        if self.use_bias:
            self.bb = self.add_weight(name="bias", shape=(input_shape[-1]), initializer=self.bb_init, trainable=True)
        super(ChannelAffine, self).build(input_shape)

    def call(self, inputs, **kwargs):
        return inputs * self.ww + self.bb if self.use_bias else inputs * self.ww

    def compute_output_shape(self, input_shape):
        return input_shape

    def get_config(self):
        config = super(ChannelAffine, self).get_config()
        config.update({"use_bias": self.use_bias, "weight_init_value": self.weight_init_value})
        return config


# NOT using
def channel_affine(inputs, use_bias=True, weight_init_value=1, name=""):
    ww_init = keras.initializers.Constant(weight_init_value) if weight_init_value != 1 else "ones"
    nn = keras.backend.expand_dims(inputs, 1)
    nn = keras.layers.DepthwiseConv2D(1, depthwise_initializer=ww_init, use_bias=use_bias, name=name)(nn)
    return keras.backend.squeeze(nn, 1)


def res_mlp_block(inputs, channels_mlp_dim, activation="gelu", name=None):
    nn = ChannelAffine(use_bias=True, name=name + "norm_1")(inputs)
    nn = keras.layers.Permute((2, 1), name=name + "permute_1")(nn)
    nn = keras.layers.Dense(nn.shape[-1], name=name + "token_mixing")(nn)
    nn = keras.layers.Permute((2, 1), name=name + "permute_2")(nn)
    nn = ChannelAffine(use_bias=False, name=name + "gamma_1")(nn)
    # Drop
    token_out = keras.layers.Add(name=name + "add_1")([inputs, nn])

    nn = ChannelAffine(use_bias=True, name=name + "norm_2")(token_out)
    nn = keras.layers.Dense(channels_mlp_dim, name=name + "channel_mixing_1")(nn)
    nn = keras.layers.Activation(activation, name=name + activation)(nn)
    nn = keras.layers.Dense(inputs.shape[-1], name=name + "channel_mixing_2")(nn)
    channel_out = ChannelAffine(use_bias=False, name=name + "gamma_2")(nn)
    # Drop
    nn = keras.layers.Add(name=name + "add_2")([channel_out, token_out])
    return nn


def ResMLP(
    num_blocks,
    patch_size,
    hidden_dim,
    channels_mlp_dim,
    input_shape=(224, 224, 3),
    num_classes=0,
    activation="gelu",
    sam_rho=0,
    dropout=0,
    drop_connect_rate=0,
    classifier_activation="softmax",
    pretrained="imagenet",
    model_name="resmlp",
    kwargs=None,
):
    inputs = keras.Input(input_shape)
    nn = keras.layers.Conv2D(hidden_dim, kernel_size=patch_size, strides=patch_size, padding="valid", name="stem")(inputs)
    nn = keras.layers.Reshape([-1, hidden_dim])(nn)

    # drop_connect_s, drop_connect_e = drop_connect_rate if isinstance(drop_connect_rate, (list, tuple)) else [drop_connect_rate, drop_connect_rate]
    for ii in range(num_blocks):
        name = "{}_{}_".format("ResMlpBlock", str(ii + 1))
        nn = res_mlp_block(nn, channels_mlp_dim=channels_mlp_dim, activation=activation, name=name)
    nn = ChannelAffine(name="pre_head_norm")(nn)

    if num_classes > 0:
        # nn = tf.reduce_mean(nn, axis=1)
        nn = keras.layers.GlobalAveragePooling1D()(nn)
        if dropout > 0 and dropout < 1:
            nn = keras.layers.Dropout(dropout)(nn)
        nn = keras.layers.Dense(num_classes, activation=classifier_activation, name="predictions")(nn)

    if sam_rho != 0:
        from keras_mlp import SAMModel

        model = SAMModel(inputs, nn, name=model_name)
    else:
        model = keras.Model(inputs, nn, name=model_name)
    reload_model_weights(model, input_shape, pretrained)
    return model


def reload_model_weights(model, input_shape=(224, 224, 3), pretrained="imagenet"):
    pretrained_dd = {
        "resmlp12": ["imagenet"],
        "resmlp24": ["imagenet"],
        "resmlp36": ["imagenet"],
        "resmlp_b24": ["imagenet", "imagenet22k"],
    }
    if model.name not in pretrained_dd or pretrained not in pretrained_dd[model.name]:
        print(">>>> No pretraind available, model will be random initialized")
        return

    pre_url = "https://github.com/leondgarse/keras_mlp/releases/download/resmlp/{}_{}.h5"
    url = pre_url.format(model.name, pretrained)
    file_name = os.path.basename(url)
    try:
        pretrained_model = keras.utils.get_file(file_name, url, cache_subdir="models")
    except:
        print("[Error] will not load weights, url not found or download failed:", url)
        return
    else:
        print(">>>> Load pretraind from:", pretrained_model)
        model.load_weights(pretrained_model, by_name=True, skip_mismatch=True)


def ResMLP12(input_shape=(224, 224, 3), num_classes=1000, activation="gelu", classifier_activation="softmax", pretrained="imagenet", **kwargs):
    num_blocks = 12
    patch_size = 16
    hidden_dim = 384
    channels_mlp_dim = hidden_dim * 4
    return ResMLP(**locals(), model_name="resmlp12", **kwargs)


def ResMLP24(input_shape=(224, 224, 3), num_classes=1000, activation="gelu", classifier_activation="softmax", pretrained="imagenet", **kwargs):
    num_blocks = 24
    patch_size = 16
    hidden_dim = 384
    channels_mlp_dim = hidden_dim * 4
    return ResMLP(**locals(), model_name="resmlp24", **kwargs)


def ResMLP36(input_shape=(224, 224, 3), num_classes=1000, activation="gelu", classifier_activation="softmax", pretrained="imagenet", **kwargs):
    num_blocks = 36
    patch_size = 16
    hidden_dim = 384
    channels_mlp_dim = hidden_dim * 4
    return ResMLP(**locals(), model_name="resmlp36", **kwargs)


def ResMLP_B24(input_shape=(224, 224, 3), num_classes=1000, activation="gelu", classifier_activation="softmax", pretrained="imagenet", **kwargs):
    num_blocks = 24
    patch_size = 8
    hidden_dim = 768
    channels_mlp_dim = hidden_dim * 4
    return ResMLP(**locals(), model_name="resmlp_b24", **kwargs)
