#!/usr/bin/env python
import rospy
from std_msgs.msg import Int32
from geometry_msgs.msg import PoseStamped, Pose
from styx_msgs.msg import TrafficLightArray, TrafficLight
from styx_msgs.msg import Lane
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
from light_classification.tl_classifier import TLClassifier
from scipy.spatial import distance
import tf
import cv2
import yaml
import numpy as np
import timeit


STATE_COUNT_THRESHOLD = 3

class TLDetector(object):
    def __init__(self):
        rospy.init_node('tl_detector', log_level=rospy.DEBUG)

        self.pose = None
        self.waypoints = None 
        self.camera_image = None
        self.lights = []
        self.stop_lines=[]

        sub1 = rospy.Subscriber('/current_pose', PoseStamped, self.pose_cb)
        sub2 = rospy.Subscriber('/base_waypoints', Lane, self.waypoints_cb)

        '''
        /vehicle/traffic_lights provides you with the location of the traffic light in 3D map space and
        helps you acquire an accurate ground truth data source for the traffic light
        classifier by sending the current color state of all traffic lights in the
        simulator. When testing on the vehicle, the color state will not be available. You'll need to
        rely on the position of the light and the camera image to predict it.
        '''
        sub3 = rospy.Subscriber('/vehicle/traffic_lights', TrafficLightArray, self.traffic_cb)
        sub6 = rospy.Subscriber('/image_color', Image, self.image_cb)

        config_string = rospy.get_param("/traffic_light_config")
        self.config = yaml.load(config_string)

        self.upcoming_red_light_pub = rospy.Publisher('/traffic_waypoint', Int32, queue_size=1)

        self.bridge = CvBridge()
        self.light_classifier = TLClassifier()
        self.listener = tf.TransformListener()

        self.state = TrafficLight.UNKNOWN
        self.last_state = TrafficLight.UNKNOWN
        self.last_wp = -1
        self.state_count = 0

        rospy.logdebug("initialized....")

        rospy.spin()

    def pose_cb(self, msg):
        self.pose = msg

    def waypoints_cb(self, waypoints):
        rospy.logdebug("waypoints received....")
        self.waypoints = waypoints

    def traffic_cb(self, msg):
        self.lights = msg.lights

    def image_cb(self, msg):
        """Identifies red lights in the incoming camera image and publishes the index
            of the waypoint closest to the red light's stop line to /traffic_waypoint

        Args:
            msg (Image): image from car-mounted camera

        """

        self.has_image = True
        self.camera_image = msg
        
        start = timeit.default_timer()
        light_wp, state = self.process_traffic_lights()
        end = timeit.default_timer()
        '''
        Publish upcoming red lights at camera frequency.
        Each predicted state has to occur `STATE_COUNT_THRESHOLD` number
        of times till we start using it. Otherwise the previous stable state is
        used.
        '''
        if self.state != state:
            self.state_count = 0
            self.state = state
        elif self.state_count >= STATE_COUNT_THRESHOLD:
            self.last_state = self.state
            light_wp = light_wp if (state == TrafficLight.RED or state == TrafficLight.YELLOW) else -1
            self.last_wp = light_wp
            self.upcoming_red_light_pub.publish(Int32(light_wp))
        else:
            self.upcoming_red_light_pub.publish(Int32(self.last_wp))
        self.state_count += 1
		
    def get_coordinates_vector(self,position):
        return np.asarray([position.x, position.y, position.z])

    def get_closest_waypoint(self, pose):
        """Identifies the closest path waypoint to the given position
            https://en.wikipedia.org/wiki/Closest_pair_of_points_problem
        Args:
            pose (Pose): position to match a waypoint to

        Returns:
            int: index of the closest waypoint in self.waypoints

        """
        if self.waypoints is not None:
            node = self.get_coordinates_vector(pose.position)
            waypoints = np.asarray([[waypoint.pose.pose.position.x, waypoint.pose.pose.position.y, waypoint.pose.pose.position.z] for waypoint in
                                    self.waypoints.waypoints])
            nearest_index = distance.cdist([node], waypoints).argmin()
        else:
            rospy.logdebug("no  waypoints")

        return nearest_index

    def get_light_state(self, light):
        """Determines the current color of the traffic light

        Args:
            light (TrafficLight): light to classify

        Returns:
            int: ID of traffic light color (specified in styx_msgs/TrafficLight)

        """
        if(not self.has_image):
            self.prev_light_loc = None
            rospy.logdebug("returning false")
            return False
        cv_image = self.bridge.imgmsg_to_cv2(self.camera_image, "rgb8")
        #Get classification
        return self.light_classifier.get_classification(cv_image)

    def process_traffic_lights(self):
        """Finds closest visible traffic light, if one exists, and determines its
            location and color

        Returns:
            int: index of waypoint closes to the upcoming stop line for a traffic light (-1 if none exists)
            int: ID of traffic light color (specified in styx_msgs/TrafficLight)

        """
        light = None
        light_wp = -1
        state = TrafficLight.UNKNOWN

        # List of positions that correspond to the line to stop in front of for a given intersection
        stop_line_positions = self.config['stop_line_positions']
	
        closest_waypoint_fn = self.get_closest_stoplight_waypoint
        closest_waypoints =  [closest_waypoint_fn(stop_line_position) for stop_line_position in stop_line_positions]

        self.stop_lines.extend(closest_waypoints)

        # Find the nearest waypoint
        #print("self pose ",self.pose)
        min_idx_dist = 150
        if(self.pose):
            car_position = self.get_closest_waypoint(self.pose.pose)
            for i, stop_line_idx in enumerate(self.stop_lines):
                idx_dist = stop_line_idx - car_position

                if 0 < idx_dist < min_idx_dist:
                    light = i
                    min_idx_dist = idx_dist
                    light_wp = stop_line_idx
                    break
                else:
                    light=None

            #light=1

        #TODO find the closest visible traffic light (if one exists)
        if light is not None:
            state = self.get_light_state(light)
            return light_wp, state
        #self.waypoints = None
        return -1, TrafficLight.UNKNOWN
    
    def get_closest_stoplight_waypoint(self, stop_line_position):
        pose = Pose()
        pose.position.x = stop_line_position[0]
        pose.position.y = stop_line_position[1]
        pose.position.z = 0

        closest_waypoint = self.get_closest_waypoint(pose)
        return closest_waypoint

if __name__ == '__main__':
    try:
        TLDetector()
    except rospy.ROSInterruptException:
        rospy.logerr('Could not start traffic node.')
