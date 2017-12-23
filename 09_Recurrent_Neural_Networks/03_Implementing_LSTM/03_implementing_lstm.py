#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Implementing an LSTM RNN Model
# ------------------------------
#  Here we implement an LSTM model on all a data set of Shakespeare works.
#

from __future__ import print_function

import os
import re
import string
import requests
import numpy as np
import collections
import random
import pickle

import matplotlib.pyplot as plt
import tensorflow as tf


# Set RNN Parameters
min_word_freq = 5  # Trim the less frequent words off
rnn_size = 128  # RNN Model size
embedding_size = 100  # Word embedding size
epochs = 20  # Number of epochs to cycle through data
batch_size = 100  # Train on this many examples at once
learning_rate = 0.001  # Learning rate
training_seq_len = 50  # how long of a word group to consider
save_every = 1000  # How often to save model checkpoints
eval_every = 50  # How often to evaluate the test sentences
prime_texts = ['thou art more', 'to be or not to', 'wherefore art thou']


# Download/store Shakespeare data
data_dir = 'temp'
data_file = 'shakespeare.txt'
model_path = 'shakespeare_model'
full_model_dir = os.path.join(data_dir, model_path)

# Declare punctuation to remove, everything except hyphens and apostrophes
punctuation = string.punctuation
punctuation = ''.join([x for x in punctuation if x not in ['-', "'"]])

# Make Model Directory
if not os.path.exists(full_model_dir):
  os.makedirs(full_model_dir)

# Make data directory
if not os.path.exists(data_dir):
  os.makedirs(data_dir)

print('Loading Shakespeare Data')
# Check if file is downloaded.
if not os.path.isfile(os.path.join(data_dir, data_file)):
  print('Not found, downloading Shakespeare texts from www.gutenberg.org')
  shakespeare_url = 'http://www.gutenberg.org/cache/epub/100/pg100.txt'
  # Get Shakespeare text
  response = requests.get(shakespeare_url)
  shakespeare_file = response.content
  # Decode binary into string
  input_text = shakespeare_file.decode('utf-8')
  # Drop first few descriptive paragraphs.
  input_text = input_text[7675:]
  # Remove newlines
  input_text = input_text.replace('\r\n', '')
  input_text = input_text.replace('\n', '')

  # Write to file
  with open(os.path.join(data_dir, data_file), 'w') as out_conn:
    out_conn.write(input_text)
else:
  # If file has been saved, load from that file
  with open(os.path.join(data_dir, data_file), 'r') as file_conn:
    input_text = file_conn.read().replace('\n', '')

# Clean text
print('Cleaning Text')
input_text = re.sub(r'[{}]'.format(punctuation), ' ', input_text)
input_text = re.sub('\s+', ' ', input_text).strip().lower()

# Build word vocabulary function
def build_vocab(text, min_word_freq):
  word_counts = collections.Counter(text.split(' '))
  # limit word counts to those more frequent than cutoff
  word_counts = {key: val for key, val in word_counts.items() if val > min_word_freq}
  # Create vocab --> index mapping
  words = word_counts.keys()
  vocab_to_ix_dict = {key: (ix + 1) for ix, key in enumerate(words)}
  # Add unknown key --> 0 index
  vocab_to_ix_dict['unknown'] = 0
  # Create index --> vocab mapping
  ix_to_vocab_dict = {val: key for key, val in vocab_to_ix_dict.items()}
  return ix_to_vocab_dict, vocab_to_ix_dict

# Build Shakespeare vocabulary
print('Building Shakespeare Vocab')
ix2vocab, vocab2ix = build_vocab(input_text, min_word_freq)
vocab_size = len(ix2vocab) + 1
print('Vocabulary Length = {}'.format(vocab_size))
# Sanity Check
assert (len(ix2vocab) == len(vocab2ix))

# Convert text to word vectors
s_text_words = input_text.split(' ')
s_text_ix = []
for ix, x in enumerate(s_text_words):
  try:
    s_text_ix.append(vocab2ix[x])
  except:
    s_text_ix.append(0)
s_text_ix = np.array(s_text_ix)


# Define LSTM RNN Model
class LSTM_Model():
  def __init__(self, embedding_size, rnn_size, batch_size, learning_rate,
               training_seq_len, vocab_size, infer_sample=False):
    self.embedding_size = embedding_size
    self.rnn_size = rnn_size
    self.vocab_size = vocab_size
    self.infer_sample = infer_sample
    self.learning_rate = learning_rate

    if infer_sample:
      self.batch_size = 1
      self.training_seq_len = 1
    else:
      self.batch_size = batch_size
      self.training_seq_len = training_seq_len

    self.x_data = tf.placeholder(tf.int32, [self.batch_size, self.training_seq_len])
    self.y_output = tf.placeholder(tf.int32, [self.batch_size, self.training_seq_len])

    with tf.variable_scope('lstm_vars'):
      # Softmax Output Weights
      W = tf.get_variable('W', [self.rnn_size, self.vocab_size], tf.float32, tf.random_normal_initializer())
      b = tf.get_variable('b', [self.vocab_size], tf.float32, tf.constant_initializer(0.0))

      # Define Embedding
      embedding_mat = tf.get_variable('embedding_mat', [self.vocab_size, self.embedding_size],
                                      tf.float32, tf.random_normal_initializer())

      embedding_output = tf.nn.embedding_lookup(embedding_mat, self.x_data)
      rnn_inputs = tf.split(axis=1, num_or_size_splits=self.training_seq_len, value=embedding_output)
      rnn_inputs_trimmed = [tf.squeeze(x, [1]) for x in rnn_inputs]

    # If we are inferring (generating text), we add a 'loop' function
    # Define how to get the i+1-th input from the i-th output
    def inferred_loop(prev, count):
      # Apply hidden layer
      prev_transformed = tf.matmul(prev, W) + b
      # Get the index of the output (also don't run the gradient)
      #
      # About stop_gradient:
      # https://stackoverflow.com/questions/33727935/how-to-use-stop-gradient-in-tensorflow/33729320#33729320
      prev_symbol = tf.stop_gradient(tf.argmax(prev_transformed, 1))
      # Get embedded vector
      output = tf.nn.embedding_lookup(embedding_mat, prev_symbol)
      return output

    # The decoder makes a of basic LSTM cells.
    self.lstm_cell = tf.contrib.rnn.BasicLSTMCell(num_units=self.rnn_size)
    self.initial_state = self.lstm_cell.zero_state(self.batch_size, tf.float32)

    # Notes:
    # Despite the fancy name, this model is not exactly seq2seq. It's just a cool way to
    # train and sample an ordinary LSTM layer. Here's how it works:
    #
    # - In training, `infer_sample=False`, hence `inferred_loop` is not applied.
    #   In this case, the input to each cell is coming from `decoder_inputs=rnn_inputs_trimmed`.
    #   The call is basically equivalent to `static_rnn`.
    #
    # - In testing, `inferred_loop` is giving the input to feed to each next cell, overwriting `decoder_inputs`.
    #   It does the same transformation as logits during training, effectively copying `self.logit_output` op,
    #   and returning the corresponding word embedding.
    #
    #   The outputs will then go through the dense layer once again,
    #   producing the same words that have been fed to LSTM.
    #
    #   Invariant: LSTM output must go through the dense layer before it notes a word.
    #
    #   BUT: `self.training_seq_len=1` in testing, so this whole mess is actually not used.
    #        https://github.com/nfmcclure/tensorflow_cookbook/pull/114
    #
    # One more application of this trick:
    # https://github.com/sherjilozair/char-rnn-tensorflow/blob/master/model.py
    decoder = tf.contrib.legacy_seq2seq.rnn_decoder
    outputs, last_state = decoder(decoder_inputs=rnn_inputs_trimmed,
                                  initial_state=self.initial_state,
                                  cell=self.lstm_cell,
                                  loop_function=inferred_loop if infer_sample else None)
    # Non inferred outputs
    output = tf.reshape(tf.concat(axis=1, values=outputs), [-1, self.rnn_size])
    # Logits and output
    self.logit_output = tf.matmul(output, W) + b
    self.model_output = tf.nn.softmax(self.logit_output)

    # This loss simply sums up the `nn_ops.sparse_softmax_cross_entropy_with_logits`.
    # All three lists have just one item, so it's not necessary here.
    #
    # By the way, in the older versions of tensorflow (an in the book) it seems to be:
    # tf.nn.seq2seq.rnn_decoder
    # tf.nn.seq2seq.sequence_loss_by_example
    loss_fun = tf.contrib.legacy_seq2seq.sequence_loss_by_example
    loss = loss_fun(logits=[self.logit_output],
                    targets=[tf.reshape(self.y_output, [-1])],
                    weights=[tf.ones([self.batch_size * self.training_seq_len])])
    self.cost = tf.reduce_sum(loss) / (self.batch_size * self.training_seq_len)
    self.final_state = last_state
    gradients, _ = tf.clip_by_global_norm(tf.gradients(self.cost, tf.trainable_variables()), 4.5)
    optimizer = tf.train.AdamOptimizer(self.learning_rate)
    self.train_op = optimizer.apply_gradients(zip(gradients, tf.trainable_variables()))

  def sample(self, sess, words=ix2vocab, vocab=vocab2ix, num=10, prime_text='thou art'):
    state = sess.run(self.lstm_cell.zero_state(1, tf.float32))
    word_list = prime_text.split()
    for word in word_list[:-1]:
      x = np.zeros((1, 1))
      x[0, 0] = vocab[word]
      state = sess.run(self.final_state, feed_dict={self.x_data: x, self.initial_state: state})

    out_sentence = prime_text
    word = word_list[-1]
    for n in range(num):
      x = np.zeros((1, 1))
      x[0, 0] = vocab[word]
      model_output, state = sess.run([self.model_output, self.final_state],
                                     feed_dict={self.x_data: x, self.initial_state: state})
      sample = np.argmax(model_output[0])
      if sample == 0:
        break
      word = words[sample]
      out_sentence = out_sentence + ' ' + word
    return out_sentence


# Define LSTM Model
lstm_model = LSTM_Model(embedding_size, rnn_size, batch_size, learning_rate,
                        training_seq_len, vocab_size)

# Tell TensorFlow we are reusing the scope for the testing
with tf.variable_scope(tf.get_variable_scope(), reuse=True):
  test_lstm_model = LSTM_Model(embedding_size, rnn_size, batch_size, learning_rate,
                               training_seq_len, vocab_size, infer_sample=True)

# Create model saver
saver = tf.train.Saver(tf.global_variables())

# Create batches for each epoch
num_batches = int(len(s_text_ix) / (batch_size * training_seq_len)) + 1
# Split up text indices into subarrays, of equal size
batches = np.array_split(s_text_ix, num_batches)
# Reshape each split into [batch_size, training_seq_len]
batches = [np.resize(x, [batch_size, training_seq_len]) for x in batches]

# Train model
with tf.Session() as sess:
  sess.run(tf.global_variables_initializer())

  train_loss = []
  iteration_count = 1
  for epoch in range(epochs):
    # Shuffle word indices
    random.shuffle(batches)
    # Create targets from shuffled batches
    targets = [np.roll(x, -1, axis=1) for x in batches]
    # Run a through one epoch
    print('Starting Epoch #{} of {}.'.format(epoch + 1, epochs))
    # Reset initial LSTM state every epoch
    state = sess.run(lstm_model.initial_state)
    for ix, batch in enumerate(batches):
      feed_dict = {lstm_model.x_data: batch, lstm_model.y_output: targets[ix]}
      c, h = lstm_model.initial_state
      feed_dict[c] = state.c
      feed_dict[h] = state.h

      temp_loss, state, _ = sess.run([lstm_model.cost, lstm_model.final_state, lstm_model.train_op],
                                     feed_dict=feed_dict)
      train_loss.append(temp_loss)

      # Print status every 10 gens
      if iteration_count % 10 == 0:
        summary_nums = (iteration_count, epoch + 1, ix + 1, num_batches + 1, temp_loss)
        print('Iteration: {}, Epoch: {}, Batch: {} out of {}, Loss: {:.3f}'.format(*summary_nums))

      # Save the model and the vocab
      if iteration_count % save_every == 0:
        # Save model
        model_file_name = os.path.join(full_model_dir, 'model')
        saver.save(sess, model_file_name, global_step=iteration_count)
        print('Model Saved To: {}'.format(model_file_name))
        # Save vocabulary
        dictionary_file = os.path.join(full_model_dir, 'vocab.pkl')
        with open(dictionary_file, 'wb') as dict_file_conn:
          pickle.dump([vocab2ix, ix2vocab], dict_file_conn)

      if iteration_count % eval_every == 0:
        for sample in prime_texts:
          print(test_lstm_model.sample(sess, ix2vocab, vocab2ix, num=20, prime_text=sample))

      iteration_count += 1

# Plot loss over time
plt.plot(train_loss, 'k-')
plt.title('Sequence to Sequence Loss')
plt.xlabel('Generation')
plt.ylabel('Loss')
plt.show()
