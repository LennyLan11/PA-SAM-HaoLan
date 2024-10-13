# import os
# import argparse
# import numpy as np
# import torch
# import torch.optim as optim
# import torch.nn as nn
# import torch.nn.functional as F
# from torch.autograd import Variable
# import matplotlib.pyplot as plt
# import cv2
# import random
# from typing import Dict, List, Tuple

# from segment_anything_training import sam_model_registry
# from segment_anything_training.modeling import TwoWayTransformer, MaskDecoder

# from utils.dataloader import get_im_gt_name_dict, create_dataloaders, RandomHFlip, Resize, LargeScaleJitter
# from utils.losses import loss_masks, loss_masks_whole, loss_masks_whole_uncertain, loss_boxes, loss_uncertain, loss_iou
# from utils.function import show_heatmap, show_anns, show_heatmap_ax, show_anns_ax, show_mask, show_points, show_box, show_only_points, compute_iou, compute_boundary_iou
# import utils.misc as misc

# from model.mask_decoder_pa import MaskDecoderPA

# import logging
# import csv
# import time

# import warnings
# warnings.filterwarnings('ignore')


# def get_args_parser():
#     parser = argparse.ArgumentParser('PA-SAM', add_help=False)

#     parser.add_argument("--output", type=str, required=True, 
#                         help="Path to the directory where masks and checkpoints will be output")
#     parser.add_argument("--logfile", type=str, default=None, 
#                         help="Path to save the log file")
#     parser.add_argument("--model-type", type=str, default="vit_l", 
#                         help="The type of model to load, in ['vit_h', 'vit_l', 'vit_b']")
#     parser.add_argument("--checkpoint", type=str, required=True, 
#                         help="The path to the SAM checkpoint to use for mask generation.")
#     parser.add_argument("--device", type=str, default="cuda", 
#                         help="The device to run generation on.")

#     parser.add_argument('--seed', default=42, type=int)
#     parser.add_argument('--learning_rate', default=1e-3, type=float)
#     parser.add_argument('--start_epoch', default=0, type=int)
#     parser.add_argument('--lr_drop_epoch', default=10, type=int)
#     parser.add_argument('--max_epoch_num', default=21, type=int)
#     parser.add_argument('--input_size', default=[1024,1024], type=list)
#     parser.add_argument('--batch_size_train', default=4, type=int)
#     parser.add_argument('--batch_size_valid', default=1, type=int)
#     parser.add_argument('--model_save_fre', default=4, type=int)

#     parser.add_argument('--world_size', default=1, type=int,
#                         help='number of distributed processes')
#     parser.add_argument('--dist_url', default='env://', help='url used to set up distributed training')
#     parser.add_argument('--rank', default=0, type=int,
#                         help='number of distributed processes')
#     parser.add_argument('--local_rank', type=int, help='local rank for dist')
#     parser.add_argument('--find_unused_params', default=True)

#     parser.add_argument('--eval', action='store_true')
#     parser.add_argument('--visualize', action='store_true')
#     parser.add_argument("--restore-model", type=str,
#                         help="The path to the pa_decoder training checkpoint for evaluation")

#     return parser.parse_args()

# # commented for 3 channel
# # class ChannelReducer(nn.Module):
# #     def __init__(self):
# #         super(ChannelReducer, self).__init__()
# #         self.conv = nn.Conv2d(5, 3, kernel_size=1, stride=1, padding=0)

# #     def forward(self, x):
# #         return self.conv(x)
# class ChannelReducer(nn.Module):
#     def __init__(self):
#         super(ChannelReducer, self).__init__()

#     def forward(self, x):
#         return x[:, :3, :, :]  

# class SAMWith5Channels(nn.Module):
#     def __init__(self, sam_model, model_type):
#         super(SAMWith5Channels, self).__init__()
#         self.channel_reducer = ChannelReducer()
#         self.sam = sam_model

#         # Replace the original mask decoder with our custom one
#         # transformer_dim = self.sam.mask_decoder.transformer_dim
#         # transformer = self.sam.mask_decoder.transformer
#         self.sam.mask_decoder = MaskDecoderPA(model_type)
    

#     def forward(self, x, labels):
#         x = self.channel_reducer(x)

#         #imgs = x.permute(0, 2, 3, 1).cpu().numpy()
#         imgs = x.permute(0, 2, 3, 1).cpu().detach().numpy()

#          # input prompt
#         # if self.training:
#         #     input_keys = ['box','point','noise_mask']
#         # else:
#         #     input_keys = ['box']

#         # input prompt
#         if self.training:
#             input_keys = ['box','point','noise_mask','box+point','box+noise_mask','point+noise_mask','box+point+noise_mask']
#         else:
#             input_keys = ['box']
#         labels_box = misc.masks_to_boxes(labels[:,0,:,:])
#         try:
#             labels_points = misc.masks_sample_points(labels[:,0,:,:])
#         except:
#             # less than 10 points
#             input_keys = ['box','noise_mask','box+noise_mask']
#         labels_256 = F.interpolate(labels, size=(256, 256), mode='bilinear')
#         labels_noisemask = misc.masks_noise(labels_256)

#         batched_input = []
#         gt_boxes = []
#         for b_i in range(len(imgs)):
#             dict_input = dict()
#             input_image = torch.as_tensor(imgs[b_i].astype(dtype=np.uint8), device=self.sam.device).permute(2, 0, 1).contiguous()
#             dict_input['image'] = input_image 
#             input_type = random.choice(input_keys)
#             gt_boxes.append((labels_box[b_i:b_i+1]/1024).clamp(min=0.0, max=1.0))  
#             noise_box = misc.box_noise(labels_box[b_i:b_i+1], box_noise_scale=1)
#             if  'box' in input_type:    
#                 dict_input['boxes'] = labels_box[b_i:b_i+1] 
#             elif 'point' in input_type:   
#                 point_coords = labels_points[b_i:b_i+1]
#                 dict_input['point_coords'] = point_coords
#                 dict_input['point_labels'] = torch.ones(point_coords.shape[1], device=point_coords.device)[None,:]
#             elif 'noise_mask' in input_type:   
#                 dict_input['mask_inputs'] = labels_noisemask[b_i:b_i+1]
#             else:
#                 raise NotImplementedError
#             dict_input['original_size'] = imgs[b_i].shape[:2]
#             dict_input['label'] = labels[b_i:b_i+1]
#             batched_input.append(dict_input)

#         with torch.no_grad():
#             batched_output, interm_embeddings = self.sam.forward_for_prompt_adapter(batched_input, multimask_output=False)
        
#         gt_boxes = torch.cat(gt_boxes, 0)
#         batch_len = len(batched_output)
#         encoder_embedding = torch.cat([batched_output[i_l]['encoder_embedding'] for i_l in range(batch_len)], dim=0)
#         image_pe = [batched_output[i_l]['image_pe'] for i_l in range(batch_len)]
#         sparse_embeddings = [batched_output[i_l]['sparse_embeddings'] for i_l in range(batch_len)]
#         dense_embeddings = [batched_output[i_l]['dense_embeddings'] for i_l in range(batch_len)]
#         image_record = [batched_output[i_l]['image_record'] for i_l in range(batch_len)]
#         input_images = batched_output[0]['input_images']

#         masks_sam, iou_preds, uncertain_maps, final_masks, coarse_masks, refined_masks, box_preds = self.sam.mask_decoder(
#             image_embeddings=encoder_embedding,
#             image_pe=image_pe,
#             sparse_prompt_embeddings=sparse_embeddings,
#             dense_prompt_embeddings=dense_embeddings,
#             multimask_output=False,
#             interm_embeddings=interm_embeddings,
#             image_record=image_record,
#             prompt_encoder=self.sam.prompt_encoder,
#             input_images=input_images
#         )

#         return masks_sam, iou_preds, uncertain_maps, final_masks, coarse_masks, refined_masks, box_preds

# def main(train_datasets, valid_datasets, args):

#     misc.init_distributed_mode(args)
#     print('world size: {}'.format(args.world_size))
#     print('rank: {}'.format(args.rank))
#     print('local_rank: {}'.format(args.local_rank))
#     print("args: " + str(args) + '\n')

#     seed = args.seed + misc.get_rank()
#     torch.manual_seed(seed)
#     np.random.seed(seed)
#     random.seed(seed)

#     ### --- Step 1: Train or Valid dataset ---
#     if not args.eval:
#         print("--- create training dataloader ---")
#         train_im_gt_list = get_im_gt_name_dict(train_datasets, flag="train")
#         train_dataloaders, train_datasets = create_dataloaders(train_im_gt_list,
#                                                         my_transforms = [
#                                                                     RandomHFlip(),
#                                                                     LargeScaleJitter()
#                                                                     ],
#                                                         batch_size = args.batch_size_train,
#                                                         training = True)
#         print(len(train_dataloaders), " train dataloaders created")

#     print("--- create valid dataloader ---")
#     valid_im_gt_list = get_im_gt_name_dict(valid_datasets, flag="valid")
#     valid_dataloaders, valid_datasets = create_dataloaders(valid_im_gt_list,
#                                                           my_transforms = [
#                                                                         Resize(args.input_size)
#                                                                     ],
#                                                           batch_size=args.batch_size_valid,
#                                                           training=False)
#     print(len(valid_dataloaders), " valid dataloaders created")
    
#     ### --- Step 2: DistributedDataParallel---
#     sam = sam_model_registry[args.model_type](checkpoint=args.checkpoint)
#     sam_5_channel = SAMWith5Channels(sam, args.model_type)
#     if torch.cuda.is_available():
#         sam_5_channel.cuda()
#     sam_5_channel = torch.nn.parallel.DistributedDataParallel(sam_5_channel, device_ids=[args.gpu], find_unused_parameters=args.find_unused_params)
#     sam_5_channel_without_ddp = sam_5_channel.module

#     ### --- Step 3: Train or Evaluate ---
#     if not args.eval:
#         print("--- define optimizer ---")
#         params_to_optimize = list(sam_5_channel_without_ddp.channel_reducer.parameters()) + list(sam_5_channel_without_ddp.sam.mask_decoder.parameters())
#         optimizer = optim.Adam(params_to_optimize, lr=args.learning_rate, betas=(0.9, 0.999), eps=1e-08, weight_decay=0)

#         lr_scheduler = torch.optim.lr_scheduler.StepLR(optimizer, args.lr_drop_epoch)
#         lr_scheduler.last_epoch = args.start_epoch

#         train(args, sam_5_channel, optimizer, train_dataloaders, valid_dataloaders, lr_scheduler)
#     else:
#         # sam = sam_model_registry[args.model_type](checkpoint=args.checkpoint)
#         # _ = sam.to(device=args.device)
#         # sam = torch.nn.parallel.DistributedDataParallel(sam, device_ids=[args.gpu], find_unused_parameters=args.find_unused_params)

#         if args.restore_model:
#             print("restore model from:", args.restore_model)
#             if torch.cuda.is_available():
#                 # sam_5_channel_without_ddp.load_state_dict(torch.load(args.restore_model)['model_state_dict'],strict=False)
#                 sam_5_channel_without_ddp.load_state_dict(torch.load(args.restore_model), strict=False)

#             else:
#                 sam_5_channel_without_ddp.load_state_dict(torch.load(args.restore_model,map_location="cpu")['model_state_dict'])

#         evaluate(args, sam_5_channel_without_ddp, sam, valid_dataloaders, args.visualize, print_func=print)

# def train(args, sam_5_channel, optimizer, train_dataloaders, valid_dataloaders, lr_scheduler):
#     if misc.is_main_process():
#         os.makedirs(args.output, exist_ok=True)
#         if  not args.logfile:
#             args.logfile = args.output + '/' + args.output[10:] + '_train.txt'
#         if os.path.exists(args.logfile):
#             os.remove(args.logfile)
#         logging.basicConfig(filename=args.logfile, level=logging.INFO)
    
#     def print(*args, **kwargs):
#         output = ' '.join(str(arg) for arg in args)
#         logging.info(output)
#         built_in_print(*args, **kwargs)
#     built_in_print = __builtins__.print

#     epoch_start = args.start_epoch
#     epoch_num = args.max_epoch_num
#     train_num = len(train_dataloaders)

#     sam_5_channel.train()
#     _ = sam_5_channel.to(device=args.device)
    
#     for epoch in range(epoch_start,epoch_num): 
#         print("epoch:   ",epoch, "  learning rate:  ", optimizer.param_groups[0]["lr"])
#         os.environ["CURRENT_EPOCH"] = str(epoch)
#         metric_logger = misc.MetricLogger(delimiter="  ")
#         train_dataloaders.batch_sampler.sampler.set_epoch(epoch)

#         for data in metric_logger.log_every(train_dataloaders, 20, logger=args.logfile, print_func=print):
#             # inputs, labels = data['image'], data['label']
#             # as of 09/17, 5channel will cause issues
#             inputs, labels = data['image_5channel'], data['label']
           
#             if torch.cuda.is_available():
#                 inputs = inputs.cuda()
#                 labels = labels.cuda()

#             masks_sam, iou_preds, uncertain_maps, final_masks, coarse_masks, refined_masks, box_preds = sam_5_channel(inputs, labels)


#             loss_mask, loss_dice = loss_masks_whole(masks_sam, labels/255.0, len(masks_sam)) 
#             loss = loss_mask + loss_dice

#             loss_mask_final, loss_dice_final = loss_masks_whole_uncertain(coarse_masks, refined_masks, labels/255.0, uncertain_maps, len(final_masks))
#             loss = loss + (loss_mask_final + loss_dice_final)     
#             loss_uncertain_map, gt_uncertain = loss_uncertain(uncertain_maps, labels)  
#             loss = loss + loss_uncertain_map

#             loss_dict = {"loss_mask": loss_mask, "loss_dice":loss_dice, 
#                                "loss_mask_final": loss_mask_final, "loss_dice_final": loss_dice_final, 
#                                "loss_uncertain_map": loss_uncertain_map}

#             # reduce losses over all GPUs for logging purposes
#             loss_dict_reduced = misc.reduce_dict(loss_dict)
#             losses_reduced_scaled = sum(loss_dict_reduced.values())
#             loss_value = losses_reduced_scaled.item()

#             optimizer.zero_grad()
#             loss.backward()

#             optimizer.step()

#             metric_logger.update(training_loss=loss_value, **loss_dict_reduced)


#         print("Finished epoch:      ", epoch)
#         metric_logger.synchronize_between_processes()
#         print("Averaged stats:", metric_logger)
#         train_stats = {k: meter.global_avg for k, meter in metric_logger.meters.items() if meter.count > 0}

#         lr_scheduler.step()
#         test_stats = evaluate(args, sam_5_channel, None, valid_dataloaders, print_func=print)
#         train_stats.update(test_stats) 

#         if epoch % args.model_save_fre == 0:
#             # model_name = "/epoch_"+str(epoch)+".pth"
#             # print('come here save at', args.output + model_name)
#             # misc.save_on_master(net.module.state_dict(), args.output + model_name)
#             checkpoint = {
#             'model_state_dict': sam_5_channel.state_dict(),
#             'optimizer_state_dict': optimizer.state_dict(),
#             'epoch': epoch
#             }
#             model_name = "/epoch_"+str(epoch)+".pth"
#             print('come here save at', args.output + model_name)
#             misc.save_on_master(checkpoint,  args.output + model_name)

#     # Finish training
#     print("Training Reaches The Maximum Epoch Number")
    
#     # merge sam and pa_decoder
#     # if misc.is_main_process():
#     #     sam_ckpt = torch.load(args.checkpoint)
#     #     pa_decoder = torch.load(args.output + model_name)
#     #     sam_ckpt.update({k.replace('mask_decoder', 'mask_decoder_ori'): v for k, v in sam_ckpt.items() if 'mask_decoder' in k})
#     #     for key in pa_decoder.keys():
#     #         sam_key = 'mask_decoder.'+key
#     #         sam_ckpt[sam_key] = pa_decoder[key]
#     #     model_name = "/sam_pa_epoch_"+str(epoch)+".pth"
#     #     torch.save(sam_ckpt, args.output + model_name)

# def evaluate(args, sam_5_channel_without_ddp, sam, valid_dataloaders, visualize=False, print_func=print):
    
#     print = print_func

#     if args.eval and not args.visualize:
#         if  not args.logfile:
#             args.logfile = args.output + '/' + args.output[10:] + '_eval.txt'
#         if os.path.exists(args.logfile):
#             os.remove(args.logfile)
#         logging.basicConfig(filename=args.logfile, level=logging.INFO)

#         def print(*args, **kwargs):
#             output = ' '.join(str(arg) for arg in args)
#             logging.info(output)
#             built_in_print(*args, **kwargs)
#         built_in_print = __builtins__.print
    
#     sam_5_channel_without_ddp.eval()
#     print("Validating...")
#     test_stats = {}

#     for k in range(len(valid_dataloaders)):
#         metric_logger = misc.MetricLogger(delimiter="  ")
#         valid_dataloader = valid_dataloaders[k]
#         print('valid_dataloader len:', len(valid_dataloader))
        
#         iou_result = []
#         biou_result = []
#         img_id = []
#         #dataset_name = ['DIS','COIFT','HRSOD','ThinObject']
#         # dataset_name = ['DIS','COIFT','HRSOD','ThinObject','Oregon', 'Washington']
#         dataset_name = ['Oregon', 'Washington','BodegaBay','Alaska']
#         total_time = 0

#         for data_val in metric_logger.log_every(valid_dataloader,1000,logger=args.logfile, print_func=print):
#             imidx_val, inputs_val, labels_val, shapes_val, labels_ori = data_val['imidx'], data_val['image'], data_val['label'], data_val['shape'], data_val['ori_label']
#             image_5channel = data_val['image_5channel']

#             if torch.cuda.is_available():
#                 inputs_val = inputs_val.cuda()
#                 labels_val = labels_val.cuda()
#                 labels_ori = labels_ori.cuda()
            
#                 image_5channel = image_5channel.cuda()

#             imgs = inputs_val.permute(0, 2, 3, 1).cpu().numpy()
#             labels_box = misc.masks_to_boxes(labels_val[:,0,:,:])
 

#             masks_sam, iou_preds, uncertain_maps, final_masks, coarse_masks, refined_masks, box_preds = sam_5_channel_without_ddp(image_5channel, labels_val)

#             iou = compute_iou(masks_sam,labels_ori)
#             boundary_iou = compute_boundary_iou(masks_sam,labels_ori)
            
#             if visualize:
#                 print("visualize")
#                 os.makedirs(args.output, exist_ok=True)
#                 masks_pa_vis = (F.interpolate(masks_sam.detach(), (1024, 1024), mode="bilinear", align_corners=False) > 0).cpu()
#                 for ii in range(len(imgs)):
#                     base = data_val['imidx'][ii].item()
#                     print('base:', base)
#                     save_base = os.path.join(args.output, str(k)+'_'+ str(base))
#                     # potential fix to correct file name
#                     ori_im_path = data_val['ori_im_path'][ii]##8/28
#                     ori_image_name = ori_im_path.split('/')[-1]##8/28
#                     print(f'ori_image_name: {ori_image_name} $$')
#                     save_base_ori_name =  os.path.join(args.output, ori_image_name)##8/28
#                     save_base = save_base_ori_name ##8/28
#                     name_add_index = False##8/28
#                     imgs_ii = imgs[ii].astype(dtype=np.uint8)
#                     show_iou = torch.tensor([iou.item()])
#                     show_boundary_iou = torch.tensor([boundary_iou.item()])
#                     show_anns(masks_pa_vis[ii], None, labels_box[ii].cpu(), None, save_base , imgs_ii, show_iou, show_boundary_iou)

#             loss_dict = {"val_iou_"+str(k): iou, "val_boundary_iou_"+str(k): boundary_iou}
#             loss_dict_reduced = misc.reduce_dict(loss_dict)
#             metric_logger.update(**loss_dict_reduced)


#         print('============================')
#         # gather the stats from all processes
#         metric_logger.synchronize_between_processes()
#         print("Averaged stats:", metric_logger)
#         resstat = {k: meter.global_avg for k, meter in metric_logger.meters.items() if meter.count > 0}
#         test_stats.update(resstat)


#     return test_stats

# if __name__ == "__main__":

#     ### --------------- Configuring the Train and Valid datasets ---------------
#     # torchrun --nproc_per_node=1 train.py --checkpoint ./pretrained_checkpoint/sam_vit_l_0b3195.pth --model-type vit_l --output ./output/res0917OR --learning_rate 0.0005
#     # for training use, update file name and folder
    
#     # torchrun --nproc_per_node=1 eval.py --checkpoint ./pretrained_checkpoint/sam_vit_l_0b3195.pth --model-type vit_l --output 
#     # ./output/Oregon/ --restore-model ./output/res0917OR/epoch_20.pth --eval --visualize
#     # for evaluation and vislization purpose

#     dataset_Oregon = {"name": "Oregon",
#                  "im_dir": "./data/Oregon/Oregon/train/image",
#                  "gt_dir": "./data/Oregon/Oregon/train/image",
#                  "im_ext": ".png",
#                  "gt_ext": ".png",
#                  }
#     # dataset_Washington = {"name": "Washington",
#     #              "im_dir": "./data/Washington/train/image",
#     #              "gt_dir": "./data/Washington/train/index",
#     #              "im_ext": ".png",
#     #              "gt_ext": ".png"}
#     # dataset_BodegaBay = {"name": "BodegaBay",
#     #              "im_dir": "./data/BodegaBay/BodegaBay/valid/image",
#     #              "gt_dir": "./data/BodegaBay/BodegaBay/valid/index",
#     #              "im_ext": ".png",
#     #              "gt_ext": ".png",
#     #              "im_ch4_dir": "./data/BodegaBay/BodegaBay/feature_map",
#     #              "im_ch5_dir": "./data/BodegaBay/BodegaBay/glcm"}
#     # dataset_Alaska = {"name": "Alaska",
#     #              "im_dir": "./data/Alaska/Alaska/valid/image",
#     #              "gt_dir": "./data/Alaska/Alaska/valid/index",
#     #              "im_ext": ".png",
#     #              "gt_ext": ".png",
#     #              "im_ch4_dir": "./data/Alaska/Alaska/feature_map",
#     #              "im_ch5_dir": "./data/Alaska/Alaska/glcm",}


#     # valid set
#     dataset_Oregon_val = {"name": "Oregon",
#                  "im_dir": "./data/Oregon/Oregon/valid/image",
#                  "gt_dir": "./data/Oregon/Oregon/valid/index",
#                  "im_ext": ".png",
#                  "gt_ext": ".png"
#                  }
#     # dataset_Washington_val = {"name": "Washington",
#     #              "im_dir": "./data/Washington/valid/image",
#     #              "gt_dir": "./data/Washington/valid/index",
#     #              "im_ext": ".png",
#     #              "gt_ext": ".png"}
#     # dataset_BodegaBay_val = {"name": "BodegaBay",
#     #              "im_dir": "./data/BodegaBay/BodegaBay/valid/image",
#     #              "gt_dir": "./data/BodegaBay/BodegaBay/valid/index",
#     #              "im_ext": ".png",
#     #              "gt_ext": ".png",
#     #              "im_ch4_dir": "./data/BodegaBay/BodegaBay/feature_map",
#     #              "im_ch5_dir": "./data/BodegaBay/BodegaBay/glcm",}
#     # dataset_Alaska_val = {"name": "Alaska",
#     #              "im_dir": "./data/Alaska/Alaska/valid/image",
#     #              "gt_dir": "./data/Alaska/Alaska/valid/index",
#     #              "im_ext": ".png",
#     #              "gt_ext": ".png",
#     #              "im_ch4_dir": "./data/Alaska/Alaska/feature_map",
#     #              "im_ch5_dir": "./data/Alaska/Alaska/glcm",}

#     train_datasets = [dataset_Oregon]
#     valid_datasets = [dataset_Oregon_val]
 
#     args = get_args_parser()
#     # net = MaskDecoderPA(args.model_type) 

#     main(train_datasets, valid_datasets, args)


import os
import argparse
import numpy as np
import torch
import torch.optim as optim
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable
import matplotlib.pyplot as plt
import cv2
import random
from typing import Dict, List, Tuple

from segment_anything_training import sam_model_registry
from segment_anything_training.modeling import TwoWayTransformer, MaskDecoder

from utils.dataloader import get_im_gt_name_dict, create_dataloaders, RandomHFlip, Resize, LargeScaleJitter
from utils.losses import loss_masks, loss_masks_whole, loss_masks_whole_uncertain, loss_boxes, loss_uncertain, loss_iou
from utils.function import show_heatmap, show_anns, show_heatmap_ax, show_anns_ax, show_mask, show_points, show_box, show_only_points, compute_iou, compute_boundary_iou
import utils.misc as misc

from model.mask_decoder_pa import MaskDecoderPA

import logging
import csv
import time

import warnings
warnings.filterwarnings('ignore')


def get_args_parser():
    parser = argparse.ArgumentParser('PA-SAM', add_help=False)

    parser.add_argument("--output", type=str, required=True, 
                        help="Path to the directory where masks and checkpoints will be output")
    parser.add_argument("--logfile", type=str, default=None, 
                        help="Path to save the log file")
    parser.add_argument("--model-type", type=str, default="vit_l", 
                        help="The type of model to load, in ['vit_h', 'vit_l', 'vit_b']")
    parser.add_argument("--checkpoint", type=str, required=True, 
                        help="The path to the SAM checkpoint to use for mask generation.")
    parser.add_argument("--device", type=str, default="cuda", 
                        help="The device to run generation on.")

    parser.add_argument('--seed', default=42, type=int)
    parser.add_argument('--learning_rate', default=1e-3, type=float)
    parser.add_argument('--start_epoch', default=0, type=int)
    parser.add_argument('--lr_drop_epoch', default=10, type=int)
    parser.add_argument('--max_epoch_num', default=21, type=int)
    parser.add_argument('--input_size', default=[1024,1024], type=list)
    parser.add_argument('--batch_size_train', default=4, type=int)
    parser.add_argument('--batch_size_valid', default=1, type=int)
    parser.add_argument('--model_save_fre', default=4, type=int)

    parser.add_argument('--world_size', default=1, type=int,
                        help='number of distributed processes')
    parser.add_argument('--dist_url', default='env://', help='url used to set up distributed training')
    parser.add_argument('--rank', default=0, type=int,
                        help='number of distributed processes')
    parser.add_argument('--local_rank', type=int, help='local rank for dist')
    parser.add_argument('--find_unused_params', default=True)

    parser.add_argument('--eval', action='store_true')
    parser.add_argument('--visualize', action='store_true')
    parser.add_argument("--restore-model", type=str,
                        help="The path to the pa_decoder training checkpoint for evaluation")

    return parser.parse_args()

def main(net, train_datasets, valid_datasets, args):

    misc.init_distributed_mode(args)
    print('world size: {}'.format(args.world_size))
    print('rank: {}'.format(args.rank))
    print('local_rank: {}'.format(args.local_rank))
    print("args: " + str(args) + '\n')

    seed = args.seed + misc.get_rank()
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)

    ### --- Step 1: Train or Valid dataset ---
    if not args.eval:
        print("--- create training dataloader ---")
        train_im_gt_list = get_im_gt_name_dict(train_datasets, flag="train")
        train_dataloaders, train_datasets = create_dataloaders(train_im_gt_list,
                                                        my_transforms = [
                                                                    RandomHFlip(),
                                                                    LargeScaleJitter()
                                                                    ],
                                                        batch_size = args.batch_size_train,
                                                        training = True)
        print(len(train_dataloaders), " train dataloaders created")

    print("--- create valid dataloader ---")
    valid_im_gt_list = get_im_gt_name_dict(valid_datasets, flag="valid")
    valid_dataloaders, valid_datasets = create_dataloaders(valid_im_gt_list,
                                                          my_transforms = [
                                                                        Resize(args.input_size)
                                                                    ],
                                                          batch_size=args.batch_size_valid,
                                                          training=False)
    print(len(valid_dataloaders), " valid dataloaders created")
    
    ### --- Step 2: DistributedDataParallel---
    if torch.cuda.is_available():
        net.cuda()
    net = torch.nn.parallel.DistributedDataParallel(net, device_ids=[args.gpu], find_unused_parameters=args.find_unused_params)
    net_without_ddp = net.module

 
    ### --- Step 3: Train or Evaluate ---
    if not args.eval:
        print("--- define optimizer ---")
        optimizer = optim.Adam(net_without_ddp.parameters(), lr=args.learning_rate, betas=(0.9, 0.999), eps=1e-08, weight_decay=0)
        lr_scheduler = torch.optim.lr_scheduler.StepLR(optimizer, args.lr_drop_epoch)
        lr_scheduler.last_epoch = args.start_epoch

        train(args, net, optimizer, train_dataloaders, valid_dataloaders, lr_scheduler)
    else:
        sam = sam_model_registry[args.model_type](checkpoint=args.checkpoint)
        _ = sam.to(device=args.device)
        sam = torch.nn.parallel.DistributedDataParallel(sam, device_ids=[args.gpu], find_unused_parameters=args.find_unused_params)

        if args.restore_model:
            print("restore model from:", args.restore_model)
            if torch.cuda.is_available():
                net_without_ddp.load_state_dict(torch.load(args.restore_model),strict=False)
            else:
                net_without_ddp.load_state_dict(torch.load(args.restore_model,map_location="cpu"))



        evaluate(args, net, sam, valid_dataloaders, args.visualize, print_func=print)

def train(args, net, optimizer, train_dataloaders, valid_dataloaders, lr_scheduler):
    if misc.is_main_process():
        os.makedirs(args.output, exist_ok=True)
        if  not args.logfile:
            args.logfile = args.output + '/' + args.output[10:] + '_train.txt'
        if os.path.exists(args.logfile):
            os.remove(args.logfile)
        logging.basicConfig(filename=args.logfile, level=logging.INFO)
    
    def print(*args, **kwargs):
        output = ' '.join(str(arg) for arg in args)
        logging.info(output)
        built_in_print(*args, **kwargs)
    built_in_print = __builtins__.print

    epoch_start = args.start_epoch
    epoch_num = args.max_epoch_num
    train_num = len(train_dataloaders)

    net.train()
    _ = net.to(device=args.device)
    
    sam = sam_model_registry[args.model_type](checkpoint=args.checkpoint)
    _ = sam.to(device=args.device)
    sam = torch.nn.parallel.DistributedDataParallel(sam, device_ids=[args.gpu], find_unused_parameters=args.find_unused_params)
    
    for epoch in range(epoch_start,epoch_num): 
        print("epoch:   ",epoch, "  learning rate:  ", optimizer.param_groups[0]["lr"])
        os.environ["CURRENT_EPOCH"] = str(epoch)
        metric_logger = misc.MetricLogger(delimiter="  ")
        train_dataloaders.batch_sampler.sampler.set_epoch(epoch)

        for data in metric_logger.log_every(train_dataloaders, 20, logger=args.logfile, print_func=print):
            inputs, labels = data['image'], data['label']
            if torch.cuda.is_available():
                inputs = inputs.cuda()
                labels = labels.cuda()

            imgs = inputs.permute(0, 2, 3, 1).cpu().numpy()
            
            # input prompt
            input_keys = ['box','point','noise_mask','box+point','box+noise_mask','point+noise_mask','box+point+noise_mask']
            labels_box = misc.masks_to_boxes(labels[:,0,:,:])
            try:
                labels_points = misc.masks_sample_points(labels[:,0,:,:])
            except:
                # less than 10 points
                input_keys = ['box','noise_mask','box+noise_mask']
            labels_256 = F.interpolate(labels, size=(256, 256), mode='bilinear')
            labels_noisemask = misc.masks_noise(labels_256)

            batched_input = []
            gt_boxes = []
            for b_i in range(len(imgs)):
                dict_input = dict()
                input_image = torch.as_tensor(imgs[b_i].astype(dtype=np.uint8), device=sam.device).permute(2, 0, 1).contiguous()
                dict_input['image'] = input_image 
                input_type = random.choice(input_keys)
                gt_boxes.append((labels_box[b_i:b_i+1]/1024).clamp(min=0.0, max=1.0))  
                noise_box = misc.box_noise(labels_box[b_i:b_i+1], box_noise_scale=1)
                if  'box' in input_type:    
                    dict_input['boxes'] = labels_box[b_i:b_i+1] 
                elif 'point' in input_type:   
                    point_coords = labels_points[b_i:b_i+1]
                    dict_input['point_coords'] = point_coords
                    dict_input['point_labels'] = torch.ones(point_coords.shape[1], device=point_coords.device)[None,:]
                elif 'noise_mask' in input_type:   
                    dict_input['mask_inputs'] = labels_noisemask[b_i:b_i+1]
                else:
                    raise NotImplementedError
                dict_input['original_size'] = imgs[b_i].shape[:2]
                dict_input['label'] = labels[b_i:b_i+1]
                batched_input.append(dict_input)

            with torch.no_grad():
                batched_output, interm_embeddings = sam.module.forward_for_prompt_adapter(batched_input, multimask_output=False)
            
            gt_boxes = torch.cat(gt_boxes, 0)
            batch_len = len(batched_output)
            encoder_embedding = torch.cat([batched_output[i_l]['encoder_embedding'] for i_l in range(batch_len)], dim=0)
            image_pe = [batched_output[i_l]['image_pe'] for i_l in range(batch_len)]
            sparse_embeddings = [batched_output[i_l]['sparse_embeddings'] for i_l in range(batch_len)]
            dense_embeddings = [batched_output[i_l]['dense_embeddings'] for i_l in range(batch_len)]
            image_record = [batched_output[i_l]['image_record'] for i_l in range(batch_len)]
            input_images = batched_output[0]['input_images']

            masks_sam, iou_preds, uncertain_maps, final_masks, coarse_masks, refined_masks, box_preds = net(
                image_embeddings=encoder_embedding,
                image_pe=image_pe,
                sparse_prompt_embeddings=sparse_embeddings,
                dense_prompt_embeddings=dense_embeddings,
                multimask_output=False,
                interm_embeddings=interm_embeddings,
                image_record=image_record,
                prompt_encoder=sam.module.prompt_encoder,
                input_images=input_images
            )

            loss_mask, loss_dice = loss_masks_whole(masks_sam, labels/255.0, len(masks_sam)) 
            loss = loss_mask + loss_dice

            loss_mask_final, loss_dice_final = loss_masks_whole_uncertain(coarse_masks, refined_masks, labels/255.0, uncertain_maps, len(final_masks))
            loss = loss + (loss_mask_final + loss_dice_final)     
            loss_uncertain_map, gt_uncertain = loss_uncertain(uncertain_maps, labels)  
            loss = loss + loss_uncertain_map

            loss_dict = {"loss_mask": loss_mask, "loss_dice":loss_dice, 
                               "loss_mask_final": loss_mask_final, "loss_dice_final": loss_dice_final, 
                               "loss_uncertain_map": loss_uncertain_map}

            # reduce losses over all GPUs for logging purposes
            loss_dict_reduced = misc.reduce_dict(loss_dict)
            losses_reduced_scaled = sum(loss_dict_reduced.values())
            loss_value = losses_reduced_scaled.item()

            optimizer.zero_grad()
            loss.backward()

            optimizer.step()

            metric_logger.update(training_loss=loss_value, **loss_dict_reduced)


        print("Finished epoch:      ", epoch)
        metric_logger.synchronize_between_processes()
        print("Averaged stats:", metric_logger)
        train_stats = {k: meter.global_avg for k, meter in metric_logger.meters.items() if meter.count > 0}

        lr_scheduler.step()
        test_stats = evaluate(args, net, sam, valid_dataloaders, print_func=print)
        train_stats.update(test_stats)
        
        net.train()  

        if epoch % args.model_save_fre == 0:
            model_name = "/epoch_"+str(epoch)+".pth"
            print('come here save at', args.output + model_name)
            misc.save_on_master(net.module.state_dict(), args.output + model_name)
    
    # Finish training
    print("Training Reaches The Maximum Epoch Number")
    
    # merge sam and pa_decoder
    if misc.is_main_process():
        sam_ckpt = torch.load(args.checkpoint)
        pa_decoder = torch.load(args.output + model_name)
        sam_ckpt.update({k.replace('mask_decoder', 'mask_decoder_ori'): v for k, v in sam_ckpt.items() if 'mask_decoder' in k})
        for key in pa_decoder.keys():
            sam_key = 'mask_decoder.'+key
            sam_ckpt[sam_key] = pa_decoder[key]
        model_name = "/sam_pa_epoch_"+str(epoch)+".pth"
        torch.save(sam_ckpt, args.output + model_name)

def evaluate(args, net, sam, valid_dataloaders, visualize=False, print_func=print):
    
    print = print_func

    if args.eval and not args.visualize:
        if  not args.logfile:
            args.logfile = args.output + '/' + args.output[10:] + '_eval.txt'
        if os.path.exists(args.logfile):
            os.remove(args.logfile)
        logging.basicConfig(filename=args.logfile, level=logging.INFO)

        def print(*args, **kwargs):
            output = ' '.join(str(arg) for arg in args)
            logging.info(output)
            built_in_print(*args, **kwargs)
        built_in_print = __builtins__.print
    
    net.eval()
    print("Validating...")
    test_stats = {}

    for k in range(len(valid_dataloaders)):
        metric_logger = misc.MetricLogger(delimiter="  ")
        valid_dataloader = valid_dataloaders[k]
        print('valid_dataloader len:', len(valid_dataloader))
        
        iou_result = []
        biou_result = []
        img_id = []
        dataset_name = ['Alaska','BodegaBay','Oregon','Washington']
        total_time = 0

        for data_val in metric_logger.log_every(valid_dataloader,1000,logger=args.logfile, print_func=print):
            imidx_val, inputs_val, labels_val, shapes_val, labels_ori = data_val['imidx'], data_val['image'], data_val['label'], data_val['shape'], data_val['ori_label']

            if torch.cuda.is_available():
                inputs_val = inputs_val.cuda()
                labels_val = labels_val.cuda()
                labels_ori = labels_ori.cuda()

            imgs = inputs_val.permute(0, 2, 3, 1).cpu().numpy()
            
            labels_box = misc.masks_to_boxes(labels_val[:,0,:,:])
            input_keys = ['box']
            batched_input = []
            for b_i in range(len(imgs)):
                dict_input = dict()
                input_image = torch.as_tensor(imgs[b_i].astype(dtype=np.uint8), device=sam.device).permute(2, 0, 1).contiguous()
                dict_input['image'] = input_image 
                input_type = random.choice(input_keys)
                if input_type == 'box':
                    dict_input['boxes'] = labels_box[b_i:b_i+1]      
                elif input_type == 'point':
                    point_coords = labels_points[b_i:b_i+1]
                    dict_input['point_coords'] = point_coords
                    dict_input['point_labels'] = torch.ones(point_coords.shape[1], device=point_coords.device)[None,:]
                elif input_type == 'noise_mask':
                    dict_input['mask_inputs'] = labels_noisemask[b_i:b_i+1]
                else:
                    raise NotImplementedError
                dict_input['original_size'] = imgs[b_i].shape[:2]
                dict_input['label'] = data_val['label'][b_i:b_i+1]
                batched_input.append(dict_input)

            with torch.no_grad():
                batched_output, interm_embeddings = sam.module.forward_for_prompt_adapter(batched_input, multimask_output=False)
            
            batch_len = len(batched_output)
            encoder_embedding = torch.cat([batched_output[i_l]['encoder_embedding'] for i_l in range(batch_len)], dim=0)
            image_pe = [batched_output[i_l]['image_pe'] for i_l in range(batch_len)]
            sparse_embeddings = [batched_output[i_l]['sparse_embeddings'] for i_l in range(batch_len)]
            dense_embeddings = [batched_output[i_l]['dense_embeddings'] for i_l in range(batch_len)]
            image_record = [batched_output[i_l]['image_record'] for i_l in range(batch_len)]
            input_images = batched_output[0]['input_images']

            masks_sam, iou_preds, uncertain_maps, final_masks, coarse_masks, refined_masks, box_preds = net(
                image_embeddings=encoder_embedding,
                image_pe=image_pe,
                sparse_prompt_embeddings=sparse_embeddings,
                dense_prompt_embeddings=dense_embeddings,
                multimask_output=False,
                interm_embeddings=interm_embeddings,
                image_record=image_record,
                prompt_encoder=sam.module.prompt_encoder,
                input_images=input_images
            )

            iou = compute_iou(masks_sam,labels_ori)
            boundary_iou = compute_boundary_iou(masks_sam,labels_ori)
            
            if visualize:
                print("visualize")
                os.makedirs(args.output, exist_ok=True)
                masks_pa_vis = (F.interpolate(masks_sam.detach(), (1024, 1024), mode="bilinear", align_corners=False) > 0).cpu()
                for ii in range(len(imgs)):
                    base = data_val['imidx'][ii].item()
                    print('base:', base)
                    save_base = os.path.join(args.output, str(k)+'_'+ str(base))
                    # imgs_ii = imgs[ii].astype(dtype=np.uint8)
                    # show_iou = torch.tensor([iou.item()])
                    # show_boundary_iou = torch.tensor([boundary_iou.item()])
                    # show_anns(masks_pa_vis[ii], None, labels_box[ii].cpu(), None, save_base , imgs_ii, show_iou, show_boundary_iou)
                    
                    # potential fix to correct file name
                    ori_im_path = data_val['ori_im_path'][ii]##8/28
                    ori_image_name = ori_im_path.split('/')[-1]##8/28
                    print(f'ori_image_name: {ori_image_name} $$')
                    save_base_ori_name =  os.path.join(args.output, ori_image_name)##8/28
                    save_base = save_base_ori_name ##8/28
                    name_add_index = False##8/28
                    imgs_ii = imgs[ii].astype(dtype=np.uint8)
                    show_iou = torch.tensor([iou.item()])
                    show_boundary_iou = torch.tensor([boundary_iou.item()])
                    show_anns(masks_pa_vis[ii], None, labels_box[ii].cpu(), None, save_base , imgs_ii, show_iou, show_boundary_iou)


            loss_dict = {"val_iou_"+str(k): iou, "val_boundary_iou_"+str(k): boundary_iou}
            loss_dict_reduced = misc.reduce_dict(loss_dict)
            metric_logger.update(**loss_dict_reduced)


        print('============================')
        # gather the stats from all processes
        metric_logger.synchronize_between_processes()
        print("Averaged stats:", metric_logger)
        resstat = {k: meter.global_avg for k, meter in metric_logger.meters.items() if meter.count > 0}
        test_stats.update(resstat)


    return test_stats

if __name__ == "__main__":
    dataset_Oregon = {"name": "Oregon",
                 "im_dir": "./data/Oregon/Oregon/train/image",
                 "gt_dir": "./data/Oregon/Oregon/train/image",
                 "im_ext": ".png",
                 "gt_ext": ".png"}

    dataset_Oregon_val = {"name": "Oregon",
                 "im_dir": "./data/Oregon/Oregon/valid/image",
                 "gt_dir": "./data/Oregon/Oregon/valid/index",
                 "im_ext": ".png",
                 "gt_ext": ".png"}

    train_datasets = [dataset_Oregon]
    valid_datasets = [dataset_Oregon_val]
 
    args = get_args_parser()
    net = MaskDecoderPA(args.model_type) 
    main(net, train_datasets, valid_datasets, args)
