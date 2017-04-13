import tensorflow as tf
import numpy as np
from SNLIGRU import SNLI
import sys
import matplotlib.pyplot as plt
import os

def createGRU(x_input, emb_size, emb_map_size, max_sequence, weight, bias, true_seq_size):

    # input shape: (batch_size, max_sequence, emb_size)
    x_input = tf.transpose(x_input, [1, 0, 2])  # permute max_sequence and batch_size
    # Reshape to prepare input to hidden activation
    x_input = tf.reshape(x_input, [-1, emb_size]) # (max_sequence*batch_size, emb_size)
    # Linear activation
    x_input = tf.matmul(x_input, weight) + bias

    # Define a gru cell with tensorflow
    gru_cell = tf.nn.rnn_cell.GRUCell(emb_map_size)
    # Split data because rnn cell needs a list of inputs for the RNN inner loop
    x_input = tf.split(0, max_sequence, x_input) # max_sequence * (batch_size, n_hidden)

    # Get gru cell output
    outputs, state = tf.nn.rnn(gru_cell, x_input, sequence_length=true_seq_size, dtype=tf.float32)

    # Linear activation
    # Get inner loop last output
    return state

def calculateAccuracy(batchIt, batch_size):
	count = 0
	acc = 0
	error = 0
	for batch_x_left,  batch_x_right,  batch_true_output in batchIt(batch_size):
		res = sess.run([cross_entropy, accuracy], feed_dict={x_left: batch_x_left[0], true_seq_size_left: batch_x_left[1], x_right: batch_x_right[0], true_seq_size_right: batch_x_right[1], true_output: batch_true_output, keep_prob: 1})
		card = batch_x_left[0].shape[0]
		error = error + res[0] * card
		acc = acc + res[1] * card
		count = count + card
	return(error / float(count), acc / float(count))

try: 
    os.makedirs('saved_model')
except OSError:
    if not os.path.isdir('saved_model'):
        raise

try: 
    os.makedirs('results')
except OSError:
    if not os.path.isdir('results'):
        raise

try: 
    os.makedirs('summaries')
except OSError:
    if not os.path.isdir('summaries'):
        raise

snli = SNLI()

# Model Parameters
emb_size = 300
max_sequence = 100
emb_map_size = 100
nlp_hidden_size = 200
n_classes = 3
learning_rate = 0.001
batch_size = 3000
display_epoch = 1
max_epochs = 300

# Define weights
weights = {
    'map': tf.get_variable("weights_map_left", shape=[emb_size, emb_map_size], initializer=tf.contrib.layers.xavier_initializer()),
    'hidden_1': tf.get_variable("weights_hidden_1", shape=[nlp_hidden_size, nlp_hidden_size], initializer=tf.contrib.layers.xavier_initializer()),
    'hidden_2': tf.get_variable("weights_hidden_2", shape=[nlp_hidden_size, nlp_hidden_size], initializer=tf.contrib.layers.xavier_initializer()),
    'hidden_3': tf.get_variable("weights_hidden_3", shape=[nlp_hidden_size, nlp_hidden_size], initializer=tf.contrib.layers.xavier_initializer()),
    'out': tf.get_variable("weights_out", shape=[nlp_hidden_size, n_classes], initializer=tf.contrib.layers.xavier_initializer())
}

biases = {
    'map': tf.Variable(tf.zeros_initializer([emb_map_size])),
    'hidden_1': tf.Variable(tf.zeros_initializer([nlp_hidden_size])),
    'hidden_2': tf.Variable(tf.zeros_initializer([nlp_hidden_size])),
    'hidden_3': tf.Variable(tf.zeros_initializer([nlp_hidden_size])),
    'out': tf.Variable(tf.zeros_initializer([n_classes]))
}

embeddings = tf.Variable(snli.getEmbeddings(), trainable=False, dtype=tf.float32)

# tf Graph input
x_left = tf.placeholder(tf.int32, [None, max_sequence])
x_left_compl = tf.nn.embedding_lookup(embeddings, x_left)

x_right = tf.placeholder(tf.int32, [None, max_sequence])
x_right_compl = tf.nn.embedding_lookup(embeddings, x_right)

true_seq_size_left = tf.placeholder(tf.int32, [None])
true_seq_size_right = tf.placeholder(tf.int32, [None])

with tf.variable_scope('left') as scope:
	left_rnn = createGRU(x_left_compl, emb_size, emb_map_size, max_sequence, weights['map'], biases['map'], true_seq_size_left)
#with tf.variable_scope('right') as scope:
	scope.reuse_variables()
	right_rnn = createGRU(x_right_compl, emb_size, emb_map_size, max_sequence, weights['map'], biases['map'], true_seq_size_right)

mlp_input = tf.concat(1, [left_rnn, right_rnn])
keep_prob = tf.placeholder(tf.float32)

h1 = tf.tanh(tf.matmul(mlp_input, weights['hidden_1']) + biases['hidden_1'])
h1_d = tf.nn.dropout(h1, keep_prob)
h2 = tf.tanh(tf.matmul(h1_d, weights['hidden_2']) + biases['hidden_2'])
h2_d = tf.nn.dropout(h2, keep_prob)
h3 = tf.tanh(tf.matmul(h2_d, weights['hidden_3']) + biases['hidden_3'])
h3_d = tf.nn.dropout(h3, keep_prob)

output = tf.matmul(h3_d, weights['out']) + biases['out']
true_output = tf.placeholder(tf.float32, [None, n_classes])

cross_entropy = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(output, true_output))

optimizer = tf.train.AdamOptimizer(learning_rate=learning_rate).minimize(cross_entropy, var_list=tf.trainable_variables())

# Evaluate model
correct_pred = tf.equal(tf.argmax(output, 1), tf.argmax(true_output ,1))
accuracy = tf.reduce_mean(tf.cast(correct_pred, tf.float32))

# Initializing the variables
init = tf.initialize_all_variables()

saver = tf.train.Saver()

results = {
	
	'train_loss': [],
	'dev_loss': [],
	'train_acc': [],
	'dev_acc': []

}

# Launch the graph

gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=0.5, allow_growth = True, allocator_type="BFC")
config_proto = tf.ConfigProto(gpu_options=gpu_options, intra_op_parallelism_threads=10)

with tf.Session(config=config_proto) as sess:

	summary_writer = tf.train.SummaryWriter('./summaries/', graph=sess.graph)
	summary_writer.flush()

	sess.run(init)
	
	cur_epoch = 1
	best_epoch = 0
	best_dev_accuracy = 0
	forgiven = 0
	max_forgiven = 20
	keep_prob_v = 1

	while cur_epoch <= max_epochs:

		print ("Epoch: %d" % (cur_epoch))
		print ("Training")

		for batch_x_left, batch_x_right, batch_true_output in snli.trainNextBatch(batch_size):
			res = sess.run([optimizer], feed_dict={x_left: batch_x_left[0], true_seq_size_left: batch_x_left[1], x_right: batch_x_right[0], true_seq_size_right: batch_x_right[1], true_output: batch_true_output, keep_prob: keep_prob_v})

		if cur_epoch % display_epoch == 0:

			print ("Calculating Accuracy")
			
			train_res = calculateAccuracy(snli.trainNextBatch, batch_size)
			results['train_loss'].append(train_res[0])
			results['train_acc'].append(train_res[1])
			print ("Train Loss= %f, Accuracy= %f" % (train_res[0], train_res[1]))
			
			dev_res = calculateAccuracy(snli.devNextBatch, batch_size)
			results['dev_loss'].append(dev_res[0])
			results['dev_acc'].append(dev_res[1])
			print ("Dev Loss= %f, Accuracy= %f" % (dev_res[0], dev_res[1]))

			if(dev_res[1] > best_dev_accuracy):
				best_dev_accuracy = dev_res[1]
				best_epoch = cur_epoch
				forgiven = 0
				saver.save(sess, "./saved_model/saved_model.ckpt")
			else:
				forgiven = forgiven + 1

			if(max_forgiven == forgiven):
				break

		cur_epoch = cur_epoch + 1

	print ("Optimization Finished! Best acc %f Best epoch %d" % (best_dev_accuracy, best_epoch))

# Launch the graph
with tf.Session(config=config_proto) as sess:
	saver.restore(sess, "./saved_model/saved_model.ckpt")
	test_res = calculateAccuracy(snli.testNextBatch, batch_size)
	print ("Test Loss= %f, Accuracy= %f" % (test_res[0], test_res[1]))

ep = np.asarray(list(range(display_epoch, len(results['train_loss']) * display_epoch + 1, display_epoch)))

fig = plt.figure()
plt.plot(ep, results['train_loss'], '-', linewidth=2, color='b', label='train loss')
plt.plot(ep, results['dev_loss'], '-', linewidth=2, color='g', label='dev loss')
#fig.suptitle('Loss', fontsize=20)
plt.xlabel('epochs', fontsize=18)
plt.ylabel('loss', fontsize=16)
plt.legend(bbox_to_anchor=(1, 1), loc='lower right', ncol=2)
#plt.show()
plt.savefig('./results/loss.png')

plt.clf()

fig = plt.figure()
plt.ylim(0, 1)
plt.plot(ep, results['train_acc'], '-', linewidth=2, color='b', label='train acc')
plt.plot(ep, results['dev_acc'], '-', linewidth=2, color='g', label='dev acc')
#fig.suptitle('Accuracy', fontsize=20)
plt.xlabel('epochs', fontsize=18)
plt.ylabel('accuracy', fontsize=16)
plt.legend(bbox_to_anchor=(1, 1), loc='lower right', ncol=2)
#plt.show()
plt.savefig('./results/acc.png')

with open('./results/results', 'w') as f:
	f.write('Epoch: ' + str(best_epoch) + '\n')
	f.write('Train Loss: ' + str(results['train_loss'][best_epoch - 1]) + ', Accuracy: ' + str(results['train_acc'][best_epoch - 1]) + '\n')
	f.write('Dev Loss: ' + str(results['dev_loss'][best_epoch - 1]) + ', Accuracy: ' + str(results['dev_acc'][best_epoch - 1]) + '\n')
	f.write('Test Loss: ' + str(test_res[0]) + ', Accuracy: ' + str(test_res[1]) + '\n')