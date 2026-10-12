"""Regression tests for semantic colour merging, state integrity and static SVG.

Run with: python scripts/integrity_test.py
All scratch files use isolated temporary directories.
"""
import argparse
import hashlib
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

import cv2
import numpy as np
from PIL import Image
import state_files
from vectorize import (collapse_palette, palette_id, palette_merge, prepare,
                       trace, draft_plan, despeckle_labels, plan_regions, path_data)
from quality import profile as fidelity_profile
from svg_compat import validate, write_svg
from weak_tones import separate_weak_tones,gradient_for_component,vector_gradient_rings


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work=Path(self.temp.name)

    def quiet(self,fn,*args):
        with contextlib.redirect_stdout(io.StringIO()):return fn(*args)

    def scene(self):
        palette=np.array([[100,100,100],[104,104,104],[108,108,108]],np.uint8)
        labels=np.tile(np.arange(3,dtype=np.uint16),(12,4))
        np.savez_compressed(self.work/'prepared.npz',labels=labels,palette=palette,alpha=np.full(labels.shape,255,np.uint8))
        info={'fingerprint':palette_id(palette),'colors':[{'index':i,'pixels':int((labels==i).sum()),'rgb':c.tolist(),'hex':'#'+''.join(f'{v:02x}' for v in c)} for i,c in enumerate(palette)]}
        (self.work/'palette.json').write_text(json.dumps(info),encoding='utf-8')
        plan={'palette_fingerprint':palette_id(palette),'default':{'id':'paper','base':'#646464','roles':{'color':[0,1,2]}}}
        (self.work/'plan.json').write_text(json.dumps(plan),encoding='utf-8')
        return palette,labels

    def merge(self,source=1,target=0,plan=None,plan_out=None):
        self.quiet(palette_merge,argparse.Namespace(work=self.work,source=source,target=target,plan=plan,plan_out=plan_out))

    def snapshot(self):
        return {p.name:p.read_bytes() for p in self.work.iterdir() if p.is_file()}

    def test_regional_roles_and_local_paints(self):
        palette=np.array([[100]*3,[104]*3],np.uint8)
        labels=np.array([[0,0,1,1],[0,1,1,1]],np.uint16)
        mapping=np.array([[0]*4,[1]*4],np.uint16)
        regions=[{'roles':{'color':[0],'ink':[1]}},{'phase':'color'}]
        result,paint,merged=collapse_palette(labels,palette,{},11,np.full_like(labels,255,np.uint8),regions,mapping)
        np.testing.assert_array_equal(result[0],labels[0])
        self.assertEqual(result[1].tolist(),[1]*4)
        self.assertEqual(paint,{(1,1):'#676767'})
        self.assertEqual(merged,1)

    def test_transparent_padding_and_empty_palette_slots(self):
        # The unused middle colour must not bridge two colours beyond threshold.
        palette=np.array([[100]*3,[104]*3,[108]*3],np.uint8)
        results=[]
        for width in (3,100):
            labels=np.ones((1,width),np.uint16);labels[0,:2]=[0,2]
            alpha=np.zeros_like(labels,np.uint8);alpha[0,:2]=255
            result,paint,merged=collapse_palette(labels,palette,{},8,alpha,[{}],np.zeros_like(labels))
            self.assertEqual(merged,0)
            np.testing.assert_array_equal(result,labels)
            result,paint,merged=collapse_palette(labels,palette,{},20,alpha,[{}],np.zeros_like(labels))
            results.append(paint)
            np.testing.assert_array_equal(result[alpha==0],labels[alpha==0])
        self.assertEqual(results[0],results[1])

    def test_default_trace_preserves_local_ink(self):
        palette=np.array([[100]*3,[104]*3],np.uint8)
        labels=np.zeros((16,16),np.uint16);labels[:,12:]=1
        np.savez_compressed(self.work/'prepared.npz',labels=labels,palette=palette,alpha=np.full_like(labels,255,np.uint8))
        plan={'default':{'id':'subject','base':'#646464','roles':{'ink':[1],'color':[0]}}}
        (self.work/'plan.json').write_text(json.dumps(plan),encoding='utf-8')
        self.quiet(trace,argparse.Namespace(work=self.work,plan=self.work/'plan.json',output=self.work/'art.svg',merge_colors=11,epsilon=.978,overlap=1.49,max_bytes=0,max_paths=0,fidelity=55))
        report=json.loads((self.work/'trace-report.json').read_text())
        self.assertGreater(report['native_paths'],0)
        self.assertIn('data-tone="ink"',(self.work/'art.svg').read_text())

    def test_prepare_counts_follow_final_labels(self):
        rgb=np.full((32,32,3),100,np.uint8);rgb[16,16]=104
        Image.fromarray(rgb).save(self.work/'source.png')
        self.quiet(prepare,argparse.Namespace(input=self.work/'source.png',work=self.work,colors=2,denoise=0,seed=41,focus=[],sample_step=1,fidelity='balanced'))
        with np.load(self.work/'prepared.npz') as data:
            counts=np.bincount(data['labels'][data['alpha']>0],minlength=2)
        entries=json.loads((self.work/'palette.json').read_text())['colors']
        self.assertEqual([e['pixels'] for e in entries],counts.tolist())
        self.assertIn(0,counts)

    def test_missing_stale_and_invalid_plans_do_not_write(self):
        self.scene()
        for content in (None,'{',json.dumps({'palette_fingerprint':'stale'})):
            bad=self.work/'bad-plan.json'
            if content is not None:bad.write_text(content)
            before=self.snapshot()
            with self.assertRaises((ValueError,FileNotFoundError)):self.merge(plan=bad)
            self.assertEqual(self.snapshot(),before)

    def test_tombstone_target_rejected(self):
        self.scene();self.merge()
        before=self.snapshot()
        with self.assertRaises(ValueError):self.merge(2,1)
        self.assertEqual(self.snapshot(),before)

    def test_merge_updates_plan_and_uses_actual_counts(self):
        palette,labels=self.scene()
        info=json.loads((self.work/'palette.json').read_text())
        info['colors'][0]['pixels']=999
        (self.work/'palette.json').write_text(json.dumps(info))
        self.merge(plan=self.work/'plan.json')
        with np.load(self.work/'prepared.npz') as data:
            self.assertEqual(data['palette'][0].tolist(),[102]*3)
            fp=palette_id(data['palette'])
        plan=json.loads((self.work/'plan.json').read_text())
        self.assertEqual(plan['palette_fingerprint'],fp)
        # Default region is part of the plan and must be remapped too.
        self.assertEqual(plan['default']['roles']['color'],[0,2])
        self.merge(2,0,plan=self.work/'plan.json')

    def test_plan_output_cannot_overwrite_state(self):
        self.scene();before=self.snapshot()
        with self.assertRaises(ValueError):self.merge(plan=self.work/'plan.json',plan_out=self.work/'palette.json')
        self.assertEqual(self.snapshot(),before)

    def test_write_failure_rolls_back_every_file(self):
        self.scene();before=self.snapshot();original=state_files.os.replace;calls=0
        def fail_once(source,target):
            nonlocal calls
            calls+=1
            if calls==3:raise OSError('injected commit failure')
            return original(source,target)
        with patch.object(state_files.os,'replace',side_effect=fail_once):
            with self.assertRaises(OSError):self.merge(plan=self.work/'plan.json')
        self.assertEqual(self.snapshot(),before)

    def test_prepared_palette_requires_matching_plan_binding(self):
        self.scene()
        original=json.loads((self.work/'plan.json').read_text())
        without_binding=dict(original);without_binding.pop('palette_fingerprint')
        (self.work/'plan.json').write_text(json.dumps(without_binding))
        args=argparse.Namespace(work=self.work,plan=self.work/'plan.json',output=self.work/'art.svg',merge_colors=0,epsilon=.55,overlap=.7,max_bytes=0,max_paths=0,fidelity=100)
        with self.assertRaisesRegex(ValueError,'palette_fingerprint'):
            self.quiet(trace,args)
        self.assertFalse((self.work/'art.svg').exists())
        (self.work/'plan.json').write_text(json.dumps(original))
        info=json.loads((self.work/'palette.json').read_text());info['fingerprint']='stale'
        (self.work/'palette.json').write_text(json.dumps(info))
        with self.assertRaisesRegex(ValueError,'Palette metadata'):
            self.quiet(trace,args)

    def test_trace_write_failure_does_not_commit_partial_outputs(self):
        self.scene()
        svg=self.work/'art.svg';report=self.work/'trace-report.json'
        for path in (svg,report):path.write_bytes(b'previous successful run')
        args=argparse.Namespace(work=self.work,plan=self.work/'plan.json',output=svg,report=report,merge_colors=0,epsilon=.55,overlap=.7,max_bytes=0,max_paths=0,fidelity=100)
        before=self.snapshot();replace=state_files.os.replace;calls=0
        def fail_once(source,target):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('injected trace commit failure')
            return replace(source,target)
        with patch.object(state_files.os,'replace',side_effect=fail_once):
            with self.assertRaises(OSError):self.quiet(trace,args)
        self.assertEqual(self.snapshot(),before)

    def test_cli_default_overlap_reduces_rgb_darkening(self):
        from visual_review import render_svg,white
        palette=np.array([[242,242,242],[38,38,38],[60,130,205],[220,130,65]],np.uint8)
        h,w=128,160;yy,xx=np.indices((h,w))
        labels=((xx//6+yy//6)%4).astype(np.uint16)
        alpha=np.full((h,w),255,np.uint8)
        np.savez_compressed(self.work/'prepared.npz',labels=labels,palette=palette,alpha=alpha)
        (self.work/'plan.json').write_text(json.dumps({'palette_fingerprint':palette_id(palette),'default':{'id':'scene','base':'#f2f2f2'}}))
        baseline=palette[labels].astype(float)
        for name in ('faithful','balanced','compact'):
            prof=fidelity_profile(name);bias=[]
            for width in (prof['overlap'],1.4):
                svg=self.work/f'{name}-{width}.svg'
                args=argparse.Namespace(work=self.work,plan=self.work/'plan.json',output=svg,report=self.work/'trace-report.json',epsilon=prof['epsilon'],overlap=width,merge_colors=prof['merge_distance'],max_bytes=0,max_paths=0,fidelity=prof['fidelity'])
                self.quiet(trace,args)
                rendered,_,_=render_svg(svg,w,h)
                bias.append((white(rendered).astype(float)-baseline).mean((0,1)))
            self.assertTrue(np.all(bias[0]>bias[1]+4),f'{name}: {bias}')
            self.assertTrue(np.all(bias[0]>-12),f'{name}: excessive darkening {bias[0]}')

    def test_auto_merge_diameter_preserves_close_tonal_steps(self):
        palette=np.array([[254,245,215],[252,236,209]],np.uint8)
        labels=np.array([[0,0,1,1]],np.uint16)
        regions=[{'phase':'color'}];mapping=np.zeros_like(labels)
        alpha=np.full_like(labels,255,np.uint8)
        _,_,merged=collapse_palette(labels,palette,{},12,alpha,regions,mapping)
        self.assertEqual(merged,1)
        limited,_,merged=collapse_palette(labels,palette,{},12,alpha,regions,mapping,max_diameter=9.8)
        self.assertEqual(merged,0)
        np.testing.assert_array_equal(limited,labels)

    def test_weak_tone_recolor_uses_original_without_erasing_ink(self):
        from visual_review import render_svg,white
        h,w=200,256
        palette=np.array([[255,248,225],[254,237,209],[65,65,65]],np.uint8)
        labels=np.zeros((h,w),np.uint16)
        cv2.circle(labels,(90,80),23,1,-1)
        labels[20:160,190:193]=2
        rgb=np.full((h,w,3),[255,248,225],np.uint8)
        rgb[labels==1]=[255,245,221]
        rgb[labels==2]=[65,65,65]
        ref=self.work/'reference.png';Image.fromarray(rgb).save(ref)
        sha=hashlib.sha256(ref.read_bytes()).hexdigest()
        np.savez_compressed(self.work/'prepared.npz',labels=labels,palette=palette,alpha=np.full((h,w),255,np.uint8))
        plan={'palette_fingerprint':palette_id(palette),'source_sha256':sha,'default':{'id':'art','base':'#fff8e1','phase':'color'},'draft_meta':{'single_region':True}}
        (self.work/'plan.json').write_text(json.dumps(plan))
        (self.work/'prepare-report.json').write_text(json.dumps({'source':str(ref),'source_sha256':sha}))
        args=argparse.Namespace(work=self.work,plan=self.work/'plan.json',output=self.work/'before.svg',epsilon=.55,overlap=.7,merge_colors=0,max_bytes=0,max_paths=0,fidelity=100,no_weak_tones=True)
        self.quiet(trace,args)
        before,_,_=render_svg(args.output,w,h)
        args.output=self.work/'after.svg';args.no_weak_tones=False
        self.quiet(trace,args)
        after,_,_=render_svg(args.output,w,h)
        original=rgb[80,90].astype(float)
        before_error=np.abs(white(before)[80,90].astype(float)-original).mean()
        after_error=np.abs(white(after)[80,90].astype(float)-original).mean()
        self.assertLess(after_error,before_error/2)
        np.testing.assert_array_equal(white(before)[40,191],white(after)[40,191])
        report=json.loads((self.work/'trace-report.json').read_text())
        self.assertEqual(report['weak_tones']['source'],'verified original source')
        self.assertGreaterEqual(report['weak_tones']['recolored_components'],1)
        self.assertGreater(report['weak_tones']['recolored_pixels'],1000)
        self.assertGreaterEqual(report['weak_tones']['gradient_components'],1)
        self.assertIn('data-soft-tone="vector-gradient"',(self.work/'after.svg').read_text())
        ref.rename(self.work/'missing.png')
        args.output=self.work/'missing-source.svg'
        self.quiet(trace,args)
        report=json.loads((self.work/'trace-report.json').read_text())
        self.assertEqual(report['weak_tones']['recolored_components'],0)
        self.assertEqual(report['weak_tones']['source'],'original source unavailable')

    def test_weak_tone_requires_soft_neighbouring_transition(self):
        h,w=90,120
        mask=np.zeros((h,w),np.uint8);cv2.circle(mask,(60,45),18,255,-1)
        source=np.full((h,w,3),[245,245,245],np.uint8)
        source[mask>0]=[210,210,210]
        _,parts,_=separate_weak_tones(mask,source,np.array([198,198,198]),max_area=10000)
        self.assertEqual(len(parts),0)
        source[mask>0]=[243,243,243]
        _,parts,changed=separate_weak_tones(mask,source,np.array([234,234,234]),max_area=10000)
        self.assertEqual(len(parts),1)
        self.assertGreater(changed,900)

    def test_fidelity_palette_capacity_increases_with_detail(self):
        self.assertEqual([fidelity_profile(name)['colors'] for name in ('compact','balanced','faithful')],
                         [32,76,112])
        self.assertLess(fidelity_profile('compact')['colors'],fidelity_profile('balanced')['colors'])
        self.assertLess(fidelity_profile('balanced')['colors'],fidelity_profile('faithful')['colors'])

    def test_soft_tone_rings_use_literal_near_continuous_pigments(self):
        height,width=100,140
        yy,xx=np.indices((height,width))
        radius=((xx-69)/22.)**2+((yy-49)/25.)**2
        mask=np.uint8(radius<=1)*255
        source=np.full((height,width,3),[255,248,225],np.uint8)
        shade=np.maximum(0,1-np.sqrt(radius))
        source[:,:,1]=np.uint8(np.clip(np.rint(248-6*shade),0,255))
        source[:,:,2]=np.uint8(np.clip(np.rint(225-10*shade),0,255))
        fit=gradient_for_component(mask,source,np.array([255,244,218],np.uint8))
        self.assertIsNotNone(fit)
        rings=vector_gradient_rings(mask,fit,20)
        self.assertGreater(len(rings),3)
        self.assertLessEqual(len(rings),21)
        self.assertEqual(tuple(rings[0][1]),tuple(fit['edge']))
        self.assertEqual(tuple(rings[-1][1]),tuple(fit['center']))
        for outer,inner in zip(rings,rings[1:]):
            self.assertTrue(np.all((inner[0]>0)<=(outer[0]>0)))
            self.assertLessEqual(int(np.max(np.abs(outer[1].astype(int)-inner[1].astype(int)))),2)

    def test_soft_tone_svg_contains_vector_bands_not_renderer_dependent_gradients(self):
        self.scene()
        svg=self.work/'bands.svg'
        plan=json.loads((self.work/'plan.json').read_text())
        plan['draft_meta']={'single_region':True}
        (self.work/'plan.json').write_text(json.dumps(plan))
        # No source available: cleanly falls back without fake gradient references.
        args=argparse.Namespace(work=self.work,plan=self.work/'plan.json',output=svg,report=self.work/'trace-report.json',merge_colors=0,epsilon=.55,overlap=.7,max_bytes=0,max_paths=0,fidelity=100,soft_tones_mode='gradient')
        self.quiet(trace,args)
        root=ET.parse(svg).getroot()
        self.assertTrue(all(e.get('fill','').startswith('#') for e in root.iter() if e.tag.endswith('path')))
        self.assertEqual(json.loads((self.work/'trace-report.json').read_text())['weak_tones']['gradient_components'],0)

    def test_draft_polygons_keep_original_coordinates(self):
        palette=np.array([[100]*3],np.uint8)
        labels=np.zeros((30,40),np.uint16);alpha=np.zeros_like(labels,np.uint8);alpha[10:20,20:30]=255
        np.savez_compressed(self.work/'prepared.npz',labels=labels,palette=palette,alpha=alpha)
        self.quiet(draft_plan,argparse.Namespace(work=self.work,output=self.work/'draft.json',min_area=1,epsilon=0,max_regions=0,ink_threshold=0,geometry='polygons'))
        plan=json.loads((self.work/'draft.json').read_text())
        vertices=np.array(plan['regions'][0]['polygons'][0])
        self.assertEqual(vertices.min(axis=0).tolist(),[20,10])
        self.assertEqual(vertices.max(axis=0).tolist(),[29,19])

    def test_local_despeckle_preserves_distant_and_invisible_pixels(self):
        palette=np.array([[100]*3,[104]*3,[240]*3],np.uint8)
        labels=np.zeros((30,40),np.uint16)
        labels[0,0]=1;labels[15,20]=1;labels[20:25,30:35]=1
        labels[10,10]=2;labels[29,39]=1
        visible=np.ones_like(labels,bool);visible[29,39]=False
        actual=despeckle_labels(labels,visible,7,palette)
        expected=labels.copy();expected[0,0]=0;expected[15,20]=0
        np.testing.assert_array_equal(actual,expected)

    def test_staging_failure_preserves_existing_files(self):
        destination=self.work/'existing';destination.write_bytes(b'original')
        blocked=self.work/'blocked';blocked.mkdir()
        with self.assertRaises(OSError):
            state_files.replace_files({destination:b'changed',blocked:b'not a directory'})
        self.assertEqual(destination.read_bytes(),b'original')
        self.assertEqual(sorted(p.name for p in self.work.iterdir()),['blocked','existing'])

    def test_static_svg_rejections_before_write(self):
        base='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="#ffffff" stroke="none"/></svg>'
        for xml in (base.replace('viewBox=','onload="void(0)" viewBox='),base.replace('0 0 10 10','0 0 nan 10'),base.replace('<rect','<a/><rect'),base.replace('width="10"','onclick="void(0)" width="10"'),base.replace('stroke="none"','stroke="none" opacity="nan"'),base.replace('fill="#ffffff"','id="shape" fill="url(#shape)"')):
            with self.subTest(xml=xml):
                root=ET.fromstring(xml)
                with self.assertRaises(ValueError):write_svg(root,self.work/'bad.svg')
                self.assertFalse((self.work/'bad.svg').exists())

    def test_static_gradient_and_metadata_allowed(self):
        root=ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs><linearGradient id="a"><stop offset="0" stop-color="#ffffff"/></linearGradient><linearGradient id="b" href="#a"/></defs><rect width="10" height="10" data-region="subject" fill="url(#b)" stroke="none"/></svg>')
        validate(root)
        root.find('.//{http://www.w3.org/2000/svg}linearGradient').set('href','#b')
        with self.assertRaises(ValueError):validate(root)

    def test_mask_draft_preserves_single_pixels_lines_and_holes(self):
        palette=np.array([[250]*3,[30]*3],np.uint8)
        labels=np.zeros((20,20),np.uint16)
        labels[2,3]=1;labels[10,1:19]=1;labels[14:18,14:18]=1;labels[15:17,15:17]=0
        np.savez_compressed(self.work/'prepared.npz',labels=labels,palette=palette,alpha=np.full_like(labels,255,np.uint8))
        self.quiet(draft_plan,argparse.Namespace(work=self.work,output=self.work/'draft.json',min_area=12,epsilon=1.5,max_regions=0,ink_threshold=0))
        plan=json.loads((self.work/'draft.json').read_text())
        regions,mapping=plan_regions(plan,labels)
        for ci in (0,1):
            owner=next(i for i,r in enumerate(regions) if r.get('include_colors')==[ci])
            np.testing.assert_array_equal(mapping==owner,labels==ci)
        self.assertLess((self.work/'draft.json').stat().st_size,2000)
        plan['regions'][0]['polygon']=[[0,0],[10,0],[10,10]]
        with self.assertRaises(ValueError):plan_regions(plan,labels)

    def test_regional_merge_budget_protects_critical_detail(self):
        palette=np.array([[100]*3,[104]*3],np.uint8)
        labels=np.array([[0,1],[0,1]],np.uint16)
        mapping=np.array([[0,0],[1,1]],np.uint16)
        regions=[{'trace':{'merge_colors':0}},{'trace':{'merge_colors':12}}]
        actual,_,count=collapse_palette(labels,palette,{},24,np.full_like(labels,255,np.uint8),regions,mapping)
        np.testing.assert_array_equal(actual[0],labels[0])
        self.assertEqual(len(set(actual[1])),1)
        self.assertEqual(count,1)
        regions[0]['trace']['merge_colors']=float('nan')
        with self.assertRaises(ValueError):collapse_palette(labels,palette,{},0,np.full_like(labels,255,np.uint8),regions,mapping)

    def test_merge_does_not_chain_distant_colours(self):
        palette=np.array([[100]*3,[108]*3,[116]*3],np.uint8)
        labels=np.array([[0,0,1,2]],np.uint16)
        actual,_,count=collapse_palette(labels,palette,{},15,np.full_like(labels,255,np.uint8),[{}],np.zeros_like(labels))
        self.assertNotEqual(actual[0,0],actual[0,3])
        self.assertEqual(count,1)

    def test_opaque_source_remains_opaque_between_contours(self):
        from visual_review import render_svg
        self.scene()
        self.quiet(trace,argparse.Namespace(work=self.work,plan=self.work/'plan.json',output=self.work/'opaque.svg',merge_colors=0,epsilon=1.5,overlap=0,max_bytes=0,max_paths=0,fidelity=0))
        rendered,_,_=render_svg(self.work/'opaque.svg')
        self.assertTrue(np.all(rendered[:,:,3]==255))

    def test_short_path_serialization_preserves_render(self):
        import pymupdf
        rng=np.random.default_rng(42)
        for _ in range(12):
            points=rng.integers(0,120,(30,2))
            expected='M'+'L'.join(f'{x/2+.25} {y/2+.25}' for x,y in points)+'Z'
            actual=path_data(points)
            def render(d):
                svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><path d="{d}" fill="#123456" fill-rule="evenodd"/></svg>'
                with pymupdf.open(stream=svg.encode(),filetype='svg') as doc:
                    return doc[0].get_pixmap(alpha=True).samples
            self.assertEqual(render(expected),render(actual))
            self.assertLess(len(actual),len(expected))
        self.assertIn('500000.25',path_data([[1000000,0],[1000001,2],[1000000,4]]))

    def test_critical_crop_blocks_numerically_good_global_candidate(self):
        from visual_review import candidate_failures
        good={'rgb_mae_white':0.,'rgb_mae_black':0.,'alpha_mae':0.,'edge_recall_2px':1.}
        bad=dict(good,edge_recall_2px=0.)
        report={'global':good,'crops':[{'id':'eyes','critical':True,'metrics':bad}]}
        self.assertEqual(candidate_failures(report,4,1,.97),['eyes: lost edges'])

    def test_candidate_search_isolated_and_requires_visual_acceptance(self):
        from visual_review import candidates,audit
        palette,labels=self.scene()
        reference=self.work/'reference.png';Image.fromarray(palette[labels]).save(reference)
        plan_path=self.work/'plan.json'
        plan=json.loads(plan_path.read_text());plan['checkpoints']=[{'id':'detail','box':[0,0,6,6]}]
        plan_path.write_text(json.dumps(plan))
        (self.work/'trace-report.json').write_bytes(b'keep baseline report')
        before=self.snapshot()
        args=argparse.Namespace(reference=reference,work=self.work,plan=plan_path,output=self.work/'candidates',fidelities='faithful,compact',max_mae=255,max_alpha_mae=255,min_edge_recall=0,max_bytes=1)
        self.quiet(candidates,args)
        self.assertEqual(self.snapshot(),before)
        report=json.loads((args.output/'candidate-report.json').read_text())
        self.assertIsNone(report['proposed_candidate'])
        self.assertIsNone(report['quality_pass'])
        self.assertTrue((args.output/'detail-candidates.png').exists())
        chosen=report['candidates'][0]
        with self.assertRaises(SystemExit):
            self.quiet(audit,argparse.Namespace(review=chosen['review_template'],comparison=chosen['comparison'],svg=chosen['svg']))
        with self.assertRaises(ValueError):self.quiet(candidates,args)


if __name__=='__main__':unittest.main()
