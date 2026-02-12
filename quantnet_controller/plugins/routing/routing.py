"""
This module is designed to get the route from source to destination in quantum networks.
"""

from enum import Enum
import types
import itertools
import networkx as nx
# from netowrkx import node_link_graph
from networkx.classes.graph import Graph
# from importlib.metadata import entry_points

import requests
import logging

logger = logging.getLogger(__name__)


class RALG (Enum):
    shortest = "Shortest"
    all_shortest = "All-Shortest"
    all_simple_paths = "All-Simple-Paths"


class NetworkRouting:
    def __init__(self, network: Graph = None, algorithm=None, **kwargs):
        self._network = network if network else nx.DiGraph()
        self._routing_algorithm = algorithm if algorithm else nx.shortest_path

    def _get_route(self, source, dest, **kwargs):
        return self.routing_algorithm(self._network, source, dest, **kwargs)

    def get_route_by_hops(self, source, dest, **kwargs):

        def get_hops(lst):
            return [(lst[i], lst[i+1]) for i in range(len(lst) - 1)]

        # Get routes
        result = self._get_route(source, dest, **kwargs)
        routes = []
        if isinstance(result, types.GeneratorType):
            routes = list(self._get_route(source, dest))
        else:
            routes = [result]

        # Decompose each route into a sequence of hops
        routes_hops = []
        for route in routes:
            routes_hops.append(get_hops(route))

        return routes_hops

    def get_routes(self, source, dest, **kwargs) -> list:
        """ Get a list of routes
        """
        result = self._get_route(source, dest, **kwargs)
        routes = []
        if isinstance(result, types.GeneratorType):
            routes = list(self._get_route(source, dest))
        else:
            routes = [result]

        return routes

    @property
    def routing_algorithm(self):
        return self._routing_algorithm

    @routing_algorithm.setter
    def routing_algorithm(self, routing_algorithm):
        self._routing_algorithm = routing_algorithm


# @nx._dispatchable
# def max_fidelity_algo(G, source=None, target=None, weight=None):
#     pass


class NetworkGenerator:
    def __init__(self, config=None, resource_fn=None, resource_mgr=None):
        self._config = config
        self._resource_callback = resource_fn if resource_fn else self._get_node_info
        self._rm = resource_mgr
        self.reset()

    def reset(self):
        self._node_info_map = {}
        self._network_graph = None
        self._ent_graph = None
        self._arp = {}

    @property
    def graph(self):
        """ Return the network graph.

        Returns
        -------
        G : NetworkX graph
        """
        if not self._network_graph:
            self._network_graph = self._create_from_topology(True)
        return self._network_graph

    @property
    def ent_graph(self):
        """ Return the network graph.

        Returns
        -------
        G : NetworkX graph
        """
        if not self._ent_graph:
            self._ent_graph = self.transform_to_ent_graph(self.graph)
        return self._ent_graph

    def add_node(self, node):
        """ Add the given node to the arp dictionary.
        """
        self._arp[node["id"]] = node
        # self._update_network_graph(node)

    @property
    def nodes(self):
        """ Return nodes from the arp dictionary.

        Returns
        -------
        nodes : list of node
        """
        nodes = []
        for k, _ in self._arp.items():
            nodes.append(k)
        return nodes

    @property
    def qnodes(self):
        """ Return qnodes from the arp dictionary.

        Returns
        -------
        nodes : list of node
        """
        nodes = []
        for k, _ in self._arp.items():
            nodes.append(k) if self._node_info_map.get(k)["systemSettings"]["type"] == "QNode" else None
        return nodes

    def refresh_topology(self):
        self._network_graph = self._create_from_topology(True)
        self._ent_graph = self.transform_to_ent_graph(self.graph)

    def get_resources(self, route: list):
        """ Return the resources associated with a given route.

        :param route: a list of nodes representing the specific route.
        :type route: list
        :return: a list of resources corresponding to the nodes along the route.
        :rtype: list
        :raises TypeError: if the route is not a list.

        """
        if not isinstance(route, list):
            raise TypeError(f"Expected argument 'route' to be of type list, but got {type(route).__name__}.")

        resources = [self.get_resource(n) for n in route]
        return resources

    def get_resource(self, node_id):
        return self._resource_callback(node_id)

    def _get_node_info(self, node_id):
        """Return the node configuration info for the given node_id
        The info is fetched from the map. If it's unavailable, return None

        :param node_id: the node id
        :type node_id: str
        :return info: the configuration info of the node
        :rtype: dict

        """
        if self._node_info_map and node_id in self._node_info_map:
            return self._rm.node_loader(self._node_info_map.get(node_id))
        return None

    def _create_from_topology(self, local=False):
        """Create the graph, arp and node configuration.

        :param local: get the topology either from remote or local
        :type local: boolean
        :return: the NetworkX graph for the network
        :rtype: networkX graph

        """

        # Create the graph for topology service
        topo = self._request_topology(local)
        self._network_graph = nx.node_link_graph(topo, edges="edges")

        # NetworkGenerator.draw_and_save_graph(self._network_graph)

        # Add nodes to arp table
        for n in topo["nodes"]:
            self.add_node(n)

        # Request node configuration and save to the hash map
        node_configs = self._request_nodeconfig(local)
        for c in node_configs:
            node_id = c["systemSettings"]["ID"]
            self._node_info_map.update({node_id: c})

        return self._network_graph

    def _request_topology(self, local=False):
        """Request the network topology.

        This function creates the network by retrieving the topology from the
        quantnet server.

        :param local: get the topology from the local or remote resource manager
        :type local: boolean

        :return: a dictionary with the link-data formatted data
        :rtype: dict

        """

        # return topo from resource manager
        if local:
            return self._rm.topology

        # return topo from remote
        try:
            # retrieve the topology
            config = self._config
            response = requests.get(f"{config.quantnet_api_base_url}/topology")
            res_json = response.json()
            if res_json["status"]["code"] != 0:
                raise Exception("API request for topology failed")
            else:
                raw_topo = res_json["value"][0]
                topology = {
                    "nodes": raw_topo.get("nodes", []),
                    "links": raw_topo.get("links") or raw_topo.get("edges", [])
                }
                if not topology["nodes"] or not topology["links"]:
                    raise Exception("topology is empty")

        except Exception as e:
            import traceback
            traceback.print_exc()
            logger.error(f"error {e}")
            raise Exception(f"{e}")

        return topology

    def _request_nodeconfig(self, local=False):
        """Request the node configurations from quantnet server topology.

        This function creates the node configurations by retrieving the
        topology from the quantnet server.

        :param local: get the configuration from local resource manager
        :type local: boolean
        :return: list of nodes
        :rtype: list

        """

        # return node configurations from resource manager
        if local:
            return self._rm.find_nodes({}, dict=True)

        # return node configurations from query
        try:
            # retrieve the node configurations
            config = self._config
            response = requests.get(f"{config.quantnet_api_base_url}/node")
            if response.json()["status"]["code"] != 0:
                raise Exception("API request for node failed")
            else:
                node_configs = response.json()["value"]
                if not node_configs:
                    raise Exception("nodes is empty")

        except Exception as e:
            import traceback
            traceback.print_exc()
            logger.error(f"error {e}")
            raise Exception(f"{self._create_network.__qualname__}:{e}")

        return node_configs

    def get_nodes_in_ent_link(self, ent_link: tuple):
        """ Return the edge property, nodes, of the given edge

        :param ent_link: entanglement link
        :type ent_link: networkX edge
        :return: List of nodes in the entanglement link
        :rtype: list

        """
        nodes_list = []
        data = self.ent_graph.get_edge_data(*ent_link)
        for k, v in data.items():
            nodes = v.get("nodes")
            if ent_link[0] != nodes[0]:
                nodes_list.append(nodes[::-1])
            else:
                nodes_list.append(nodes)
        return nodes_list

    def transform_to_ent_graph(self, graph):
        """ Transform the given graph to an entanglement graph

        :param graph: the graph to transform
        :type graph:  graph
        :return: entanglement graph
        :rtype:  graph
        """

        # entangle,ent link to path map
        ent_types = ["QNode", "QRepeater", "QSwitch", "QRouter"]
        bsm_types = ["BSMNode"]
        router_types = ["QRepeater", "QRouter"]
        node_info_map = self._node_info_map

        def get_device_type(n):
            return node_info_map.get(n)["systemSettings"]["type"]

        def is_ent_device(n):
            return get_device_type(n) in ent_types

        def is_bsm_device(n):
            return get_device_type(n) in bsm_types

        def is_router_device(n):
            return get_device_type(n) in router_types

        def generate_ent_links(bsm, g):
            """ Generate entanglement links using the given bsm in the g
            """

            def generate_bsm_tree(n, g):

                def add_children_of(n, tree, g):
                    if is_ent_device(n):
                        return

                    # Get the in edges to this node
                    in_edges = g.in_edges(n, keys=True)

                    # Extract the source nodes (neighbors)
                    in_neighbors = set([source for source, target, _ in in_edges])

                    # Add children recursively
                    for neighbor in in_neighbors:
                        # if not neighbor in tree and not is_bsm_device(neighbor):
                        if not is_bsm_device(neighbor):
                            # tree.add_node(neighbor)
                            edges = [(src, dest, key) for src, dest, key in in_edges if src == neighbor]

                            # Check existance
                            for e in edges:
                                if not tree.has_edge(*e):
                                    tree.add_node(neighbor)
                                    tree.add_edges_from(edges)
                                    add_children_of(neighbor, tree, g)

                tree = nx.MultiDiGraph()
                tree.add_node(n)
                add_children_of(n, tree, g)

                return tree

            def list_ent_links(root, t: Graph):

                def find_shortest_path(t: Graph, leaf1, leaf2, root):

                    # Find the path from leaf1 to the root
                    path_leaf1_to_root = nx.shortest_path(t, source=leaf1, target=root)

                    # Find the path from root to leaf2
                    path_root_to_leaf2 = nx.shortest_path(t, source=leaf2, target=root)

                    # Combine the two paths (excluding the root from one of them to avoid duplication)
                    full_path = path_leaf1_to_root + path_root_to_leaf2[::-1][1:]

                    return full_path

                def find_all_paths(t: Graph, leaf1, leaf2, root):

                    # Find the path from leaf1 to the root
                    paths1 = []
                    for p in nx.all_simple_paths(t, source=leaf1, target=root):
                        paths1.append(p)

                    # Find the path from root to leaf2
                    paths2 = []
                    for p in nx.all_simple_paths(t, source=leaf2, target=root):
                        paths2.append(p)

                    # Combine the two paths (excluding the root from one of them to avoid duplication)
                    full_paths = []
                    for p1 in paths1:
                        for p2 in paths2:
                            fp = p1 + p2[::-1][1:]
                            full_paths.append(fp)

                    return full_paths

                # Find all leaf nodes (nodes with only one neighbor) that are entanglement devices
                # leaf_nodes = [node for node in t.nodes() if t.degree(node) == 1 and is_ent_device(node)]
                leaf_nodes = [node for node in t.nodes() if t.in_degree(node) == 0 and is_ent_device(node)]

                # Find all pairs in the leaf_nodes list
                pairs = list(itertools.combinations(leaf_nodes, 2))

                links = []
                for p in pairs:
                    # # Find the path between two leaf nodes
                    # path = nx.shortest_path(G, source=p[0], target=p[1])

                    leaf1 = p[0]
                    leaf2 = p[1]

                    # # Find the shortest path from leaf1 to the root
                    # shortest_path = find_shortest_path(t, leaf1, leaf2, root)
                    #
                    # # Update links and map
                    # links.append((leaf1, leaf2, {'nodes': shortest_path}))
                    # # link_path_map.update({(leaf1, leaf2): shortest_path})

                    # Find all paths
                    all_paths = find_all_paths(t, leaf1, leaf2, root)
                    for p in all_paths:
                        links.append((leaf1, leaf2, {'nodes': p}))

                return links

            # Get the tree from bsm
            t = generate_bsm_tree(bsm, g)
            # draw_and_save_graph(t)

            # List all entanglement links using bsm
            ent_links = list_ent_links(bsm, t)

            return ent_links

        def extract_quantum_links(g):
            # Create a new graph with only quantum links
            d = nx.node_link_data(g, edges="edges")
            qls = [link for link in d['edges'] if link['title'] == "quantum"]
            d['edges'] = qls
            return nx.node_link_graph(d, edges="edges")

        # Convert to a graph with only quantum links
        q_graph = extract_quantum_links(graph)

        # Create the entanglemnt graph
        ent_graph = nx.MultiGraph()
        for n in q_graph.nodes():
            if is_ent_device(n):
                ent_graph.add_node(n)
            elif is_bsm_device(n):
                ent_links = generate_ent_links(n, q_graph)
                ent_graph.add_edges_from(ent_links)
            else:
                continue

        return ent_graph

    def find_route(self, src, dst, ent_link=False, **kwargs):
        """ Return the routes between src and dst nodes

        :param src: src node
        :type src: str
        :param dst: dst node
        :type dst: str
        :param ent_link: indicate if routes should cross entanglement links
        :type ent_link: boolean
        :param algorithm: the routing algorithm
        :type algorithm:  str
        :return: list of list of nodes in a route
        :rtype: list

        """

        router_types = ["QRepeater", "QRouter"]
        node_info_map = self._node_info_map

        def get_device_type(n):
            return node_info_map.get(n)["systemSettings"]["type"]

        def is_router_device(n):
            return get_device_type(n) in router_types

        def is_valid_route(hops: list):
            if len(hops) <= 1:
                return True

            for h in hops[:-1]:
                if not is_router_device(h[1]):
                    return False
            return True

        def do_filter(raw_routes) -> list:
            """ Return a list of routes that are free from duplicates
                and exclude any paths containing non-router devices in the middle.
            """
            route_set = []
            for r in raw_routes:
                valid = True
                if len(r) > 2:
                    for n in r[1:-1]:
                        valid = is_router_device(n)
                        if not valid:
                            break
                if not valid:
                    continue

                if r not in route_set:
                    route_set.append(r)

            return route_set

        def get_hops(lst):
            return [(lst[i], lst[i+1]) for i in range(len(lst) - 1)]

        # Set the algorithm and parameters if presented;
        # Otherwise use the default
        algo_dict = kwargs.get("algorithm", None)
        if algo_dict:
            if not isinstance(algo_dict, dict):
                raise TypeError("the algorithm must be dict")
            if algo_dict["name"] == RALG.shortest.value:
                algo = nx.shortest_path
            elif algo_dict["name"] == RALG.all_shortest.value:
                algo = nx.all_shortest_paths
            elif algo_dict["name"] == RALG.all_simple_paths.value:
                algo = nx.all_simple_paths
            else:
                algo = nx.shortest_path
        else:
            algo = None

        # Set the graph: entanglement or default graph
        graph = self.ent_graph if ent_link else self.graph.to_undirected()

        # Calculate routes between src and dst nodes
        try:
            # routes_in_hops = NetworkRouting(graph, algo).get_route_by_hops(src, dst)
            raw_routes = NetworkRouting(graph, algo).get_routes(src, dst)
        except nx.exception.NetworkXNoPath:
            return []
        except Exception as e:
            import traceback
            traceback.print_exc()
            logger.error(f"error {e}")
            return []

        # Handle single hop case here so we know the graph is generated
        # before any hop resolution takes place
        if src == dst:
            return raw_routes

        filtered_routes = do_filter(raw_routes) if ent_link else raw_routes

        routes_in_hops = []
        for r in filtered_routes:
            routes_in_hops.append(get_hops(r))

        # Expand nodes involved in establishing entanglement links along the routes
        routes = []
        for hops in routes_in_hops:

            subroutes = []
            for hop in hops:
                ps = self.get_nodes_in_ent_link(hop) if ent_link else [list(hop)]
                if subroutes == []:
                    subroutes = ps
                else:
                    update = []
                    for r in subroutes:
                        for p in ps:
                            nr = r + p[1:]
                            update.append(nr)
                    subroutes = update
            for s in subroutes:
                if s not in routes:
                    routes.append(s)

        return routes


def draw_and_save_graph(g, dirpath=None):

    pos = nx.spring_layout(g)
    color_map = {
        'type_QNode': 'red',
        'type_MNode': 'blue',
        'type_BSMNode': 'green',
        'type_OpticalSwitch': 'purple'
    }
    size_map = {
        'type_QNode': 500,
        'type_MNode': 500,
        'type_BSMNode': 500,
        'type_OpticalSwitch': 1000
    }

    node_colors = [color_map.get(g.nodes[node].get('node_type', 'default'), 'gray') for node in g.nodes()]
    node_sizes = [size_map.get(g.nodes[node].get('node_type', 'default'), 500) for node in g.nodes()]

    import matplotlib.pyplot as plt
    plt.figure(figsize=(10, 8))
    nx.draw(g, pos, with_labels=True, node_color=node_colors, node_size=node_sizes, edge_color='gray')
    plt.title("Topology with Additional Randomly Added Nodes")
    if dirpath:
        plt.savefig(f"{dirpath}/topo.png")
    plt.show()
